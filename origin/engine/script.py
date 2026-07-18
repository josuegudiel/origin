"""StepExecutor — ejecuta un `list[Step]` del DSL de scripting.

Es el motor unificado: cualquier comando (con `keys` o con `steps`) se ejecuta
acá vía `config.command_as_steps()`. Bloqueante; corre dentro del worker de STT
(`runtime._executor`) para serializarse contra el flujo PTT.

Soporta cancelación cooperativa via `threading.Event`. Tope duro de 100 steps
ejecutados (incluye expansiones de repeat) para evitar loops infinitos por goto.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from .config import (
    MAX_STEPS_PER_COMMAND,
    GotoStep,
    IfStep,
    KeyStep,
    LabelStep,
    RepeatStep,
    SayKeyStep,
    SayStep,
    SetStep,
    Settings,
    WaitStep,
)
from .events import EventBus, EventType

logger = logging.getLogger(__name__)

_COND_RE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$")

# SEGURIDAD (DoS): tope de wall-clock por ejecución de comando. El tope de 100
# steps NO frena un `label → wait 30000 → goto label` (cuenta 3 steps estáticos
# pero ejecuta ~33 iteraciones × 30 s ≈ 16 min bloqueando el worker). Este
# presupuesto lo corta en 60 s reales.
MAX_SCRIPT_WALL_SECONDS = 60.0


class StepExecutionState:
    """Estado mutable per-profile, persistente entre ejecuciones del mismo perfil."""

    def __init__(self) -> None:
        self.vars: dict[str, str] = {}


def eval_cond(cond: str, state: StepExecutionState) -> bool:
    """`var op rhs` con op ∈ {==, !=, >, <, >=, <=}. Sin eval Python.

    Variable no seteada → "" (falsy en string, 0 si rhs es numérico y casteable).
    """
    m = _COND_RE.match(cond)
    if not m:
        raise ValueError(f"condición inválida: {cond!r}")
    var, op, raw = m.groups()
    lhs = state.vars.get(var, "")
    rhs = raw.strip().strip("'\"")
    try:
        cmp_l: Any = float(lhs) if lhs != "" else 0.0
        cmp_r: Any = float(rhs)
    except ValueError:
        cmp_l, cmp_r = lhs, rhs
    return {
        "==": cmp_l == cmp_r,
        "!=": cmp_l != cmp_r,
        ">":  cmp_l >  cmp_r,
        "<":  cmp_l <  cmp_r,
        ">=": cmp_l >= cmp_r,
        "<=": cmp_l <= cmp_r,
    }[op]


def _resolve_say_text(s: SayStep, lang: str) -> str | None:
    if lang == "en":
        return s.text_en or s.text_es or s.text
    return s.text_es or s.text_en or s.text


class StepExecutor:
    """Bloqueante. Una instancia por orchestrator. Re-entrante via vars per-profile."""

    def __init__(
        self,
        keypress_exec: Callable[[list[str], int, bool], None],
        keypress_exec_held: Callable[[str, int, bool], None],
        tts_say: Callable[[str, str], None] | None,            # (text, lang) -> None
        tts_cancel: Callable[[], None] | None,
        set_substate: Callable[[str], None],                    # "speaking"|"running_script"
        bus: EventBus,
        settings_provider: Callable[[], Settings],
        i18n_say: Callable[[str, str], str],                    # (key, lang) -> text
        dry_run: bool = False,
    ) -> None:
        self._keypress = keypress_exec
        self._keypress_held = keypress_exec_held
        self._tts_say = tts_say
        self._tts_cancel = tts_cancel
        self._set_substate = set_substate
        self._bus = bus
        self._settings = settings_provider
        self._i18n_say = i18n_say
        self._dry_run = dry_run
        self._steps_run = 0
        self._deadline = 0.0

    def execute(
        self,
        steps: list[Any],
        state: StepExecutionState,
        lang: str,
        *,
        cancel: threading.Event,
    ) -> None:
        if not steps:
            return
        self._steps_run = 0
        self._deadline = time.monotonic() + MAX_SCRIPT_WALL_SECONDS
        labels = self._index_labels(steps)
        self._run_block(steps, labels, state, lang, cancel)

    # ------------------------------------------------------------------ internals

    def _index_labels(self, steps: list[Any]) -> dict[str, int]:
        out: dict[str, int] = {}
        for i, s in enumerate(steps):
            if isinstance(s, LabelStep):
                if s.name in out:
                    logger.warning("script_label_duplicate name=%s", s.name)
                out[s.name] = i
        return out

    def _run_block(
        self,
        steps: list[Any],
        labels: dict[str, int],
        state: StepExecutionState,
        lang: str,
        cancel: threading.Event,
    ) -> None:
        pc = 0
        while pc < len(steps):
            if cancel.is_set():
                logger.info("script_cancelled at_pc=%d", pc)
                return
            if self._steps_run >= MAX_STEPS_PER_COMMAND:
                logger.warning(
                    "script_step_limit_reached limit=%d", MAX_STEPS_PER_COMMAND
                )
                return
            if time.monotonic() >= self._deadline:
                logger.warning(
                    "script_wall_limit_reached limit=%.0fs", MAX_SCRIPT_WALL_SECONDS
                )
                return
            step = steps[pc]
            self._steps_run += 1
            new_pc = self._exec_one(step, pc, labels, state, lang, cancel)
            self._bus.emit(
                EventType.SCRIPT_STEP_EXECUTED,
                {"type": getattr(step, "type", "unknown"), "pc": pc},
            )
            pc = new_pc if new_pc is not None else pc + 1

    def _exec_one(
        self,
        step: Any,
        pc: int,
        labels: dict[str, int],
        state: StepExecutionState,
        lang: str,
        cancel: threading.Event,
    ) -> int | None:
        if isinstance(step, KeyStep):
            if step.hold_ms is not None:
                self._keypress_held(step.combo, step.hold_ms, self._dry_run)
            else:
                self._keypress([step.combo], self._settings().inter_key_delay_ms, self._dry_run)
            return None

        if isinstance(step, WaitStep):
            # `cancel.wait` permite cortar la espera al shutdown / cambio de perfil.
            cancel.wait(step.ms / 1000.0)
            return None

        if isinstance(step, SayStep):
            text = _resolve_say_text(step, lang)
            if text:
                self._say(text, lang, cancel)
            return None

        if isinstance(step, SayKeyStep):
            text = self._i18n_say(step.key, lang)
            if text:
                self._say(text, lang, cancel)
            return None

        if isinstance(step, SetStep):
            state.vars[step.var] = step.value
            return None

        if isinstance(step, IfStep):
            try:
                branch_true = eval_cond(step.cond, state)
            except ValueError as e:
                logger.warning("script_bad_cond cond=%r err=%s", step.cond, e)
                return None
            branch = step.then if branch_true else (step.else_ or [])
            self._run_block(list(branch), self._index_labels(list(branch)), state, lang, cancel)
            return None

        if isinstance(step, RepeatStep):
            inner_labels = self._index_labels(list(step.steps))
            for _ in range(step.times):
                if cancel.is_set() or self._steps_run >= MAX_STEPS_PER_COMMAND:
                    return None
                self._run_block(list(step.steps), inner_labels, state, lang, cancel)
            return None

        if isinstance(step, GotoStep):
            target = labels.get(step.label)
            if target is None:
                logger.warning("script_goto_missing label=%s", step.label)
                return None
            return target  # el outer loop hace pc += 1 vía new_pc, así que apuntamos a target directo

        if isinstance(step, LabelStep):
            return None

        logger.warning("script_unknown_step type=%s", type(step).__name__)
        return None

    def _say(self, text: str, lang: str, cancel: threading.Event) -> None:
        if self._tts_say is None:
            return
        self._set_substate("speaking")
        try:
            self._tts_say(text, lang)
        except Exception:
            logger.exception("tts_say_failed")
        finally:
            if not cancel.is_set():
                self._set_substate("running_script")
