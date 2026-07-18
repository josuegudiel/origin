"""Tests del StepExecutor — todos los step types con keypress + tts mockeados."""
from __future__ import annotations

import threading
from typing import Any

import pytest

from origin.engine.config import (
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
from origin.engine.events import EventBus, EventType
from origin.engine.script import StepExecutionState, StepExecutor, eval_cond


class _FakeTts:
    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []
        self.cancelled = 0

    def say(self, text: str, lang: str) -> None:
        self.said.append((text, lang))

    def cancel(self) -> None:
        self.cancelled += 1


@pytest.fixture
def runner():
    keys_called: list[tuple[list[str], int, bool]] = []
    held_called: list[tuple[str, int, bool]] = []
    bus = EventBus()
    tts = _FakeTts()
    states: list[str] = []
    settings = Settings()

    executor = StepExecutor(
        keypress_exec=lambda c, d, dr: keys_called.append((c, d, dr)),
        keypress_exec_held=lambda c, ms, dr: held_called.append((c, ms, dr)),
        tts_say=tts.say,
        tts_cancel=tts.cancel,
        set_substate=lambda s: states.append(s),
        bus=bus,
        settings_provider=lambda: settings,
        i18n_say=lambda key, lang: f"i18n[{key}/{lang}]",
        dry_run=False,
    )

    return {
        "executor": executor,
        "keys": keys_called,
        "held": held_called,
        "bus": bus,
        "tts": tts,
        "states": states,
    }


def _run(executor: StepExecutor, steps: list[Any]) -> StepExecutionState:
    state = StepExecutionState()
    executor.execute(steps, state, "es", cancel=threading.Event())
    return state


def test_key_step_dispatches_to_keypress(runner):
    _run(runner["executor"], [KeyStep(combo="alt+n")])
    assert runner["keys"] == [(["alt+n"], 30, False)]


def test_key_with_hold_uses_execute_held(runner):
    _run(runner["executor"], [KeyStep(combo="b", hold_ms=500)])
    assert runner["held"] == [("b", 500, False)]
    assert runner["keys"] == []


def test_wait_step_blocks_but_cancelable(runner):
    cancel = threading.Event()
    state = StepExecutionState()
    # 50 ms wait; con cancel pre-set se sale inmediato.
    cancel.set()
    runner["executor"].execute([WaitStep(ms=50)], state, "es", cancel=cancel)
    # OK si no crashea


def test_say_invokes_tts(runner):
    _run(runner["executor"], [SayStep(text_es="hola", text_en="hi")])
    assert runner["tts"].said == [("hola", "es")]


def test_say_key_resolves_via_i18n(runner):
    _run(runner["executor"], [SayKeyStep(key="tts.ack")])
    assert runner["tts"].said == [("i18n[tts.ack/es]", "es")]


def test_set_and_if_branches_true(runner):
    state = _run(
        runner["executor"],
        [
            SetStep(var="target", value="crusader"),
            IfStep(
                cond="target == 'crusader'",
                then=[SetStep(var="result", value="yes")],
            ),
        ],
    )
    assert state.vars["target"] == "crusader"
    assert state.vars["result"] == "yes"


def test_if_branches_false_goes_else(runner):
    state = _run(
        runner["executor"],
        [
            SetStep(var="a", value="1"),
            IfStep.model_validate({
                "type": "if",
                "cond": "a == '2'",
                "then": [{"type": "set", "var": "r", "value": "then"}],
                "else": [{"type": "set", "var": "r", "value": "else"}],
            }),
        ],
    )
    assert state.vars["r"] == "else"


def test_goto_jumps_to_label(runner):
    _run(
        runner["executor"],
        [
            KeyStep(combo="a"),
            GotoStep(label="end"),
            KeyStep(combo="b"),  # debería skipearse
            LabelStep(name="end"),
            KeyStep(combo="c"),
        ],
    )
    combos = [c[0][0] for c in runner["keys"]]
    assert combos == ["a", "c"]


def test_repeat_executes_n_times(runner):
    _run(runner["executor"], [RepeatStep(times=3, steps=[KeyStep(combo="a")])])
    assert len(runner["keys"]) == 3


def test_step_limit_aborts_long_loops(runner):
    # goto loop infinito — el tope MAX_STEPS_PER_COMMAND=100 corta.
    _run(
        runner["executor"],
        [LabelStep(name="loop"), KeyStep(combo="a"), GotoStep(label="loop")],
    )
    # Tope 100. Cada iteración ejecuta 3 steps; nos detenemos antes de 100.
    assert len(runner["keys"]) <= 100


def test_cancel_event_short_circuits(runner):
    cancel = threading.Event()
    state = StepExecutionState()
    cancel.set()
    runner["executor"].execute(
        [KeyStep(combo="a"), KeyStep(combo="b")], state, "es", cancel=cancel
    )
    assert runner["keys"] == []


# ---------------------------------------------------------------- eval_cond


def test_eval_cond_string_eq():
    s = StepExecutionState()
    s.vars["x"] = "yes"
    assert eval_cond("x == 'yes'", s) is True
    assert eval_cond("x != 'no'", s) is True


def test_eval_cond_numeric():
    s = StepExecutionState()
    s.vars["count"] = "5"
    assert eval_cond("count > 3", s) is True
    assert eval_cond("count <= 5", s) is True


def test_eval_cond_unset_var_is_falsy():
    s = StepExecutionState()
    assert eval_cond("nonexistent == 'x'", s) is False
    assert eval_cond("nonexistent == ''", s) is True


def test_eval_cond_bad_format_raises():
    s = StepExecutionState()
    with pytest.raises(ValueError):
        eval_cond("not a condition", s)


# ---------------------------------------------------------------- event emission


def test_script_step_event_emitted_per_step(runner):
    events: list[dict] = []
    runner["bus"].subscribe(EventType.SCRIPT_STEP_EXECUTED, lambda p: events.append(p))
    _run(runner["executor"], [KeyStep(combo="a"), WaitStep(ms=0), KeyStep(combo="b")])
    types = [e["type"] for e in events]
    assert "key" in types and "wait" in types
