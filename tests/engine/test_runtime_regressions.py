"""Tests específicos para regresiones del segundo audit (v0.3.1).

Cubre:
- `execute_command_test` deja state en READY tras ejecutar (no atascado en RUNNING_SCRIPT).
- `tts.enabled = False` corta las llamadas a Piper aunque el script tenga `say` explícito.
- Cancel de TTS via indirección (no captura bind temprano).
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from origin.engine import config as cfgmod
from origin.engine.events import EventBus
from origin.engine.runtime import Orchestrator, State


@pytest.fixture
def isolated_orch(tmp_path: Path, fixtures_dir: Path):
    """Orchestrator listo sin `start()` — para testear flujos puros del runtime."""
    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    bus = EventBus()
    orch = Orchestrator(tmp_path / "commands.yaml", bus, dry_run=True)
    # Build manualmente los módulos del script executor sin abrir mic/whisper/listeners.
    orch._build_tts()  # noqa: SLF001 — Piper missing en CI: tts será no-op
    orch._build_script_executor()  # noqa: SLF001
    yield orch, bus


def test_execute_command_test_resets_state_to_ready(isolated_orch):
    """REGRESSION: el botón Test del editor no debe dejar el state en RUNNING_SCRIPT."""
    orch, _bus = isolated_orch
    assert orch.state == State.LOADING  # estado inicial
    # Forzar a READY para simular post-load.
    orch._set_state(State.READY)  # noqa: SLF001
    orch.execute_command_test("request_landing", profile_id="flight")
    assert orch.state == State.READY, f"esperaba READY, got {orch.state}"


def test_tts_disabled_blocks_tts_calls(isolated_orch, monkeypatch):
    """REGRESSION: `set_setting(tts={enabled:False})` debe cortar TODO TTS,
    incluso si un comando tiene `say` explícito."""
    orch, _bus = isolated_orch
    say_calls: list[tuple[str, str]] = []

    # Reemplazar el método del TTS real por un spy.
    fake_tts = MagicMock()
    fake_tts.say = lambda text, lang, **kw: say_calls.append((text, lang))
    orch._tts = fake_tts  # noqa: SLF001

    # Default: tts.enabled=True → say sí se invoca.
    orch._tts_say("hola", "es")  # noqa: SLF001
    assert say_calls == [("hola", "es")]

    # Toggle a False y reintentar.
    orch._cf = orch._cf.with_settings(tts={"enabled": False})  # noqa: SLF001
    orch._settings = orch._cf.settings  # noqa: SLF001
    say_calls.clear()
    orch._tts_say("hola", "es")  # noqa: SLF001
    assert say_calls == [], "TTS no debe hablar cuando tts.enabled=False"


def test_tts_cancel_indirect_uses_current_tts(isolated_orch):
    """REGRESSION: `tts_cancel` lookup debe ser indirecto — si self._tts es None,
    no debe crashear; si es reemplazado, debe llamar al nuevo."""
    orch, _bus = isolated_orch

    # 1) Con tts None, no crashea.
    orch._tts = None  # noqa: SLF001
    orch._tts_cancel_indirect()  # noqa: SLF001 — debe ser no-op silencioso

    # 2) Con tts reasignado, llama al nuevo.
    cancel_calls = []
    fake_new_tts = MagicMock()
    fake_new_tts.cancel = lambda: cancel_calls.append(1)
    orch._tts = fake_new_tts  # noqa: SLF001
    orch._tts_cancel_indirect()  # noqa: SLF001
    assert cancel_calls == [1]


def test_ifstep_else_serializes_with_alias():
    """REGRESSION: `IfStep.else_` debe serializarse como `else:` en YAML, no `else_:`."""
    cf = cfgmod.CommandsFileV3.model_validate({
        "version": 3,
        "settings": {"active_profile": "p1"},
        "profiles": [{"id": "p1", "commands": [{
            "id": "c1", "phrases_es": ["x"], "keys": ["a"],
            "steps": [
                {"type": "set", "var": "v", "value": "1"},
                {"type": "if", "cond": "v == '1'",
                 "then": [{"type": "key", "combo": "a"}],
                 "else": [{"type": "key", "combo": "b"}]},
            ],
        }]}],
    })
    dump = cf.to_dump()
    if_step = dump["profiles"][0]["commands"][0]["steps"][1]
    assert "else" in if_step
    assert "else_" not in if_step
    assert if_step["else"] == [{"type": "key", "combo": "a", "hold_ms": None}] or \
           if_step["else"][0]["combo"] == "b"


def test_command_as_steps_no_invalid_say_when_command_has_no_labels(tmp_path: Path, fixtures_dir: Path):
    """REGRESSION: `command_as_steps` no debe crear SayStep con todos campos None
    cuando un comando legacy no tiene label_es/en ni say_es/en."""
    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    cf = cfgmod.load(tmp_path / "commands.yaml")
    # `reload` no tiene label_es/en/say_es/en
    cmd_reload = next(c for c in cf.get_profile("fps").commands if c.id == "reload")
    assert cmd_reload.label_es is None
    assert cmd_reload.say_es is None
    # No debe crashear; el SayStep solo se agrega si hay fallback texto.
    steps = cfgmod.command_as_steps(cmd_reload, cf.settings)
    # No SayStep porque no hay say_* ni label_*.
    from origin.engine.config import SayStep
    assert not any(isinstance(s, SayStep) for s in steps), \
        f"command_as_steps generó SayStep inválido para comando sin labels: {steps}"


def test_audio_truncation_logs_warning(tmp_path: Path, caplog):
    """REGRESSION: si el audio supera max_record_seconds, el truncado debe loguear
    para que el usuario sepa que perdió parte del audio."""
    import logging
    import numpy as np

    from origin.engine.audio import Recorder

    rec = Recorder(sample_rate=16000, max_record_seconds=1)
    # Inyectar buffer "como si" hubiera capturado 2s de audio.
    rec._buffer = [np.zeros(32000, dtype=np.float32)]  # noqa: SLF001
    rec._capturing = True  # noqa: SLF001
    with caplog.at_level(logging.WARNING):
        audio = rec.end_capture()
    assert audio.shape[0] == 16000, "debe truncar a max_samples"
    assert any("audio_truncated" in r.message for r in caplog.records), \
        "truncado debería loguear warning"


def test_restart_stream_clears_capture_buffer(monkeypatch):
    """REGRESSION: cambiar mic durante captura mezclaba audio del viejo + nuevo.

    `restart_stream` ahora debe descartar el buffer y resetear _capturing.
    """
    import sys
    import numpy as np

    # Stub mínimo de sounddevice — solo InputStream.start()/stop()/close().
    fake_sd = type("FakeSd", (), {})()
    class FakeStream:
        def start(self): pass
        def stop(self): pass
        def close(self): pass
    fake_sd.InputStream = lambda **kw: FakeStream()
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    from origin.engine.audio import Recorder
    rec = Recorder(sample_rate=16000, mic_device=None, max_record_seconds=8)
    rec.start_stream()
    rec.begin_capture()
    rec._buffer.append(np.ones(8000, dtype=np.float32))  # noqa: SLF001 — simulado
    assert rec.is_capturing()

    rec.restart_stream(mic_device=1)

    assert not rec.is_capturing(), "_capturing debe resetearse al cambiar mic"
    assert rec._buffer == [], "buffer debe limpiarse al cambiar mic"  # noqa: SLF001


def test_set_setting_disk_full_emits_config_error(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    """REGRESSION: si save_atomic falla (disk full / permission denied),
    `set_setting` debe emitir CONFIG_ERROR y NO actualizar el state in-memory."""
    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    bus = EventBus()
    errors: list[dict] = []
    from origin.engine.events import EventType
    bus.subscribe(EventType.CONFIG_ERROR, lambda p: errors.append(p))
    orch = Orchestrator(tmp_path / "commands.yaml", bus, dry_run=True)
    original_lang = orch.config.settings.active_language

    # Simular falla en save_atomic.
    monkeypatch.setattr(
        "origin.engine.config.save_atomic",
        lambda cf, path: (_ for _ in ()).throw(OSError("disk full")),
    )

    orch.set_setting(active_language="en")

    assert orch.config.settings.active_language == original_lang, \
        "state in-memory no debe actualizarse si el save falla"
    assert errors, "debe emitirse CONFIG_ERROR"
    assert "disk full" in errors[0]["error"]


def test_setting_active_profile_no_dual_emit(isolated_orch):
    """REGRESSION: `set_setting(active_profile=X)` debe emitir PROFILE_CHANGED
    una sola vez (no double-emit por el camino with_settings + set_active_profile)."""
    from origin.engine.events import EventType
    orch, bus = isolated_orch
    events: list[dict] = []
    bus.subscribe(EventType.PROFILE_CHANGED, lambda p: events.append(p))
    orch.set_setting(active_profile="fps")
    assert len(events) == 1, f"esperaba 1 emit, got {len(events)}"
    assert orch._profiles.active_id == "fps"  # noqa: SLF001
    assert orch._settings.active_profile == "fps"  # noqa: SLF001


def test_script_states_setdefault_under_lock(isolated_orch):
    """REGRESSION: `_dispatch_command` toma el state lock antes de tocar `_script_states`.

    Smoke test: dispatch concurrente desde 2 threads contra perfiles distintos.
    Si hay race condition, esto puede crashear o crear duplicados.
    """
    orch, _bus = isolated_orch
    orch._set_state(State.READY)  # noqa: SLF001

    # Dispatch de comandos en threads — simulado serializado por el lock interno.
    threads = []
    errors = []

    def run(pid: str, cmd_id: str) -> None:
        try:
            orch._profiles.set_active(pid)  # noqa: SLF001
            cmd = next(c for c in orch.config.get_profile(pid).commands if c.id == cmd_id)
            orch._dispatch_command(cmd, "es")  # noqa: SLF001
        except Exception as e:
            errors.append(e)

    for _ in range(3):
        t1 = threading.Thread(target=run, args=("flight", "request_landing"))
        t2 = threading.Thread(target=run, args=("fps", "reload"))
        threads.extend([t1, t2])
        t1.start(); t2.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors, f"errors during concurrent dispatch: {errors}"
    # `_script_states` debe tener entradas únicas por profile_id.
    assert set(orch._script_states.keys()) <= {"flight", "fps"}  # noqa: SLF001
