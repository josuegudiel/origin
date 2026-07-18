"""Tests de regresión de seguridad (auditoría #8).

Cubren los vectores encontrados en la auditoría de seguridad:
- RCE via `win+r` (perfil malicioso compartido) → whitelist de teclas endurecida
- Path traversal en nombres de voz TTS → carga de `.onnx` arbitrario
- SSRF / exfiltración via `llm.base_url`
- DoS via `goto` + `wait` largos (bloqueo del worker)
- Binary planting de piper.exe (resolución de path)
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from origin.engine import config as cfgmod
from origin.engine import keypress


# ---------------------------------------------------------------- RCE / keypress

@pytest.mark.parametrize("combo", ["win+r", "win+e", "win+x", "win+l", "win+d", "win", "super+r", "cmd+r"])
def test_windows_key_rejected(combo):
    """La tecla Windows/Super/Cmd es el vector principal de RCE (win+r → ejecutar)
    y no tiene uso legítimo en Star Citizen. Debe rechazarse siempre."""
    assert keypress.validate(combo) is not None


@pytest.mark.parametrize("combo", ["ctrl+shift+esc", "ctrl+shift+escape", "ctrl+alt+delete"])
def test_system_shortcuts_rejected(combo):
    assert keypress.validate(combo) is not None


@pytest.mark.parametrize("combo", ["alt+n", "ctrl+shift+x", "f12", "l", "n", "space", "enter"])
def test_legit_game_combos_still_accepted(combo):
    assert keypress.validate(combo) is None


def test_windows_key_never_reaches_os():
    """Aunque un combo malicioso pase por alguna capa, `execute` debe raisar
    antes de mandar la tecla al SO."""
    with pytest.raises(keypress.KeyError_):
        keypress.execute(["win+r"], dry_run=True)


def test_malicious_profile_win_r_rejected_at_load():
    """Un perfil compartido con `win+r` en un KeyStep debe rechazarse al cargar
    (defense-in-depth: feedback al importar, no fallo silencioso al ejecutar)."""
    with pytest.raises(Exception):
        cfgmod.CommandsFileV3.model_validate({
            "version": 3, "settings": {"active_profile": "p"},
            "profiles": [{"id": "p", "commands": [{
                "id": "evil", "phrases_es": ["x"],
                "steps": [{"type": "key", "combo": "win+r"}],
            }]}],
        })


def test_malicious_profile_win_r_in_keys_rejected():
    """Lo mismo para el campo `keys:` (v1/v2)."""
    with pytest.raises(Exception):
        cfgmod.CommandsFileV3.model_validate({
            "version": 3, "settings": {"active_profile": "p"},
            "profiles": [{"id": "p", "commands": [{
                "id": "evil", "phrases_es": ["x"], "keys": ["win+r"],
            }]}],
        })


# ---------------------------------------------------------------- path traversal

@pytest.mark.parametrize("stem", ["../../../etc/passwd", "..\\..\\evil", "a/b", "a\\b", "/abs"])
def test_voice_stem_traversal_rejected(stem):
    with pytest.raises(Exception):
        cfgmod.TtsSettings(voice_es=stem)


def test_voice_stem_legit_accepted():
    s = cfgmod.TtsSettings(voice_es="es_ES-mls_10246-low", voice_en="en_US-amy-low")
    assert s.voice_es == "es_ES-mls_10246-low"


# ---------------------------------------------------------------- SSRF / base_url

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/",
    "http://metadata.google.internal/",
    "file:///etc/passwd",
    "gopher://x",
    "ftp://x",
])
def test_base_url_dangerous_rejected(url):
    with pytest.raises(Exception):
        cfgmod.LlmSettings(base_url=url)


@pytest.mark.parametrize("url", [
    "http://localhost:11434",
    "http://127.0.0.1:11434",
    "https://192.168.1.5:11434",
])
def test_base_url_legit_accepted(url):
    assert cfgmod.LlmSettings(base_url=url).base_url == url


def test_llm_response_size_guard_exists():
    from origin.engine import llm
    assert llm._MAX_RESPONSE_BYTES <= 16 * 1024 * 1024


def test_llm_loopback_detection():
    from origin.engine.llm import _is_loopback_base_url
    assert _is_loopback_base_url("http://localhost:11434")
    assert _is_loopback_base_url("http://127.0.0.1:11434")
    assert not _is_loopback_base_url("http://attacker.tld")
    assert not _is_loopback_base_url("http://192.168.1.5:11434")


# ---------------------------------------------------------------- DoS scripting

def test_script_wall_clock_budget_cuts_infinite_loop(monkeypatch):
    """`label → wait → goto label` no lo frena el tope de 100 steps (cuenta 3
    estáticos). El presupuesto de wall-clock debe cortarlo."""
    from origin.engine import script as sm
    from origin.engine.config import GotoStep, LabelStep, Settings, WaitStep
    from origin.engine.events import EventBus

    monkeypatch.setattr(sm, "MAX_SCRIPT_WALL_SECONDS", 0.5)
    ex = sm.StepExecutor(
        keypress_exec=lambda *a: None, keypress_exec_held=lambda *a: None,
        tts_say=None, tts_cancel=None, set_substate=lambda s: None,
        bus=EventBus(), settings_provider=lambda: Settings(), i18n_say=lambda k, l: k,
    )
    steps = [LabelStep(name="loop"), WaitStep(ms=50), GotoStep(label="loop")]
    t0 = time.monotonic()
    ex.execute(steps, sm.StepExecutionState(), "es", cancel=threading.Event())
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"el script infinito no se cortó (tardó {elapsed:.1f}s)"


# ---------------------------------------------------------------- piper planting

def test_piper_path_frozen_only_from_bundle(monkeypatch):
    """En un build empaquetado (frozen), piper NUNCA debe resolverse desde
    %APPDATA% (escribible → binary planting). Solo desde el bundle read-only."""
    import sys

    from origin.engine import paths

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent/bundle", raising=False)
    # Con bundle inexistente y frozen=True, NO debe caer a %APPDATA%: devuelve None.
    assert paths.piper_exe_path() is None


def test_no_dangerous_eval_exec_in_engine():
    """Ningún módulo del engine debe usar eval/exec/pickle/os.system/shell=True."""
    import re

    engine_dir = Path(__file__).resolve().parent.parent.parent / "origin" / "engine"
    forbidden = re.compile(r"\beval\s*\(|\bexec\s*\(|\bpickle\b|os\.system|shell\s*=\s*True|yaml\.load\s*\(")
    hits = []
    for py in engine_dir.glob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden.search(line) and "eval_cond" not in line:
                hits.append(f"{py.name}:{i}: {line.strip()}")
    assert not hits, f"patrones peligrosos: {hits}"
