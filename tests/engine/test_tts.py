"""Tests del PiperTTS wrapper — subprocess + sounddevice mockeados."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from origin.engine.events import EventBus, EventType
from origin.engine.tts import PiperTTS


def test_no_piper_emits_done_with_error(tmp_path: Path):
    bus = EventBus()
    events: list[dict] = []
    bus.subscribe(EventType.TTS_DONE, lambda p: events.append(p))
    bus.subscribe(EventType.TTS_STARTED, lambda p: events.append(("started", p)))

    tts = PiperTTS(piper_exe=None, bundled_voices_dir=None,
                   user_voices_dir=tmp_path, voice_es="x", voice_en="x", bus=bus)
    tts.say("hola", "es")
    # No started; sí done con error.
    assert all(not (isinstance(e, tuple) and e[0] == "started") for e in events)
    assert any(e.get("error") == "piper_missing" for e in events if isinstance(e, dict))


def test_voice_missing_emits_done_with_error(tmp_path: Path):
    # Piper "presente" pero sin voces.
    fake_piper = tmp_path / "piper.exe"
    fake_piper.write_text("fake")
    bus = EventBus()
    errors: list[dict] = []
    bus.subscribe(EventType.TTS_DONE, lambda p: errors.append(p))

    tts = PiperTTS(piper_exe=fake_piper, bundled_voices_dir=tmp_path,
                   user_voices_dir=tmp_path, voice_es="missing-voice",
                   voice_en="missing-voice", bus=bus)
    tts.say("hola", "es")
    assert any(e.get("error") == "voice_missing" for e in errors)


def test_say_with_resolved_voice_starts_subprocess(tmp_path: Path):
    """Verifica que `say` con voice resuelta arranca subprocess.Popen con --model.

    Skip si sounddevice / PortAudio no están disponibles (CI Linux sin libportaudio2).
    """
    try:
        import sounddevice  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("sounddevice/PortAudio no disponible")

    fake_piper = tmp_path / "piper.exe"
    fake_piper.write_text("fake")
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "es_voice.onnx").write_bytes(b"x")
    (voices_dir / "es_voice.onnx.json").write_text("{}")

    bus = EventBus()
    tts = PiperTTS(piper_exe=fake_piper, bundled_voices_dir=voices_dir,
                   user_voices_dir=tmp_path / "user_voices", voice_es="es_voice",
                   voice_en="en_voice", bus=bus)

    with patch("origin.engine.tts.subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.read.side_effect = [b""]
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc
        tts.say("hola", "es", speed=1.0, volume=1.0)
    args = mock_popen.call_args[0][0]
    assert str(fake_piper) in args
    assert "--model" in args
    assert any("es_voice.onnx" in a for a in args)


def test_update_voices_changes_resolution(tmp_path: Path):
    bus = EventBus()
    tts = PiperTTS(piper_exe=None, bundled_voices_dir=None,
                   user_voices_dir=tmp_path, voice_es="old", voice_en="old", bus=bus)
    tts.update_voices("new_es", "new_en")
    # No falla; los nombres actualizados se usan en `say()`.
    assert tts._voice_es == "new_es"  # noqa: SLF001
    assert tts._voice_en == "new_en"  # noqa: SLF001
