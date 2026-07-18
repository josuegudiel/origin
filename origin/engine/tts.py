"""TTS local con Piper (binary).

Spawn `piper.exe` por cada `say()`, stream PCM 22050 Hz mono int16 por stdout,
reproducción con `sounddevice.RawOutputStream`. Bloqueante hasta fin de audio
o cancel (`threading.Event`).

Si el binary o las voces no están disponibles → no-op con log + emit `TTS_DONE
error=...`. No revienta el flujo del script ni el del runtime.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

from .events import EventBus, EventType

logger = logging.getLogger(__name__)


SAMPLE_RATE = 22050
CHANNELS = 1
DTYPE = "int16"
READ_CHUNK = 4096


class PiperTTS:
    def __init__(
        self,
        piper_exe: Path | None,
        bundled_voices_dir: Path | None,
        user_voices_dir: Path,
        voice_es: str,
        voice_en: str,
        bus: EventBus,
    ) -> None:
        self._piper = piper_exe
        self._bundled = bundled_voices_dir
        self._user = user_voices_dir
        self._voice_es = voice_es
        self._voice_en = voice_en
        self._bus = bus
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._stream = None

    def update_voices(self, voice_es: str, voice_en: str) -> None:
        self._voice_es = voice_es
        self._voice_en = voice_en

    # ---------------------------------------------------------------- voz lookup

    def _resolve_voice(self, lang: str) -> tuple[Path, Path] | None:
        stem = self._voice_en if lang == "en" else self._voice_es
        for base in (self._user, self._bundled):
            if base is None:
                continue
            onnx = base / f"{stem}.onnx"
            cfg = base / f"{stem}.onnx.json"
            if onnx.exists() and cfg.exists():
                return onnx, cfg
        return None

    def is_available(self, lang: str | None = None) -> bool:
        if self._piper is None or not self._piper.exists():
            return False
        if lang is None:
            return True
        return self._resolve_voice(lang) is not None

    def is_speaking(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    # ---------------------------------------------------------------- say + cancel

    def say(
        self,
        text: str,
        lang: str,
        *,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> None:
        """Bloqueante. Emite TTS_STARTED al inicio, TTS_DONE al final/cancel/error."""
        if not text.strip():
            return
        if self._piper is None or not self._piper.exists():
            logger.warning("tts_no_piper text=%r", text[:40])
            self._bus.emit(EventType.TTS_DONE, {"error": "piper_missing", "text": text})
            return
        resolved = self._resolve_voice(lang)
        if resolved is None:
            stem = self._voice_en if lang == "en" else self._voice_es
            logger.warning("tts_voice_missing voice=%s lang=%s", stem, lang)
            self._bus.emit(
                EventType.TTS_DONE,
                {"error": "voice_missing", "voice": stem, "text": text},
            )
            return
        onnx, _cfg = resolved
        length_scale = 1.0 / max(0.1, speed)
        self._cancel.clear()
        self._bus.emit(EventType.TTS_STARTED, {"text": text, "lang": lang})
        cancelled = False
        try:
            with self._lock:
                self._proc = subprocess.Popen(
                    [
                        str(self._piper),
                        "--model", str(onnx),
                        # Forma canónica del help de piper. El binario acepta
                        # --output-raw como alias, pero su parser ignora flags
                        # desconocidas en silencio — usar la canónica nos protege
                        # si el alias desaparece en una versión futura.
                        "--output_raw",
                        "--length_scale", f"{length_scale:.3f}",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            assert self._proc.stdin is not None
            assert self._proc.stdout is not None
            self._proc.stdin.write(text.encode("utf-8"))
            self._proc.stdin.close()
            cancelled = self._play_stream(self._proc.stdout, volume)
        except Exception as e:
            logger.exception("tts_say_failed")
            self._bus.emit(EventType.TTS_DONE, {"error": str(e), "text": text})
            return
        finally:
            with self._lock:
                if self._proc is not None:
                    try:
                        self._proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        self._proc.terminate()
                    self._proc = None
        self._bus.emit(EventType.TTS_DONE, {"text": text, "cancelled": cancelled})

    def _play_stream(self, stdout, volume: float) -> bool:
        """Devuelve True si se canceló."""
        try:
            import sounddevice as sd  # lazy
        except Exception:
            logger.warning("tts_no_sounddevice")
            stdout.read()
            return False
        try:
            # Procesamos en chunks pequeños para chequear cancel frecuentemente.
            stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=DTYPE)
            stream.start()
        except Exception as e:
            # Sin output device (headset desconectado, PC sin parlantes) — degradar
            # limpio: drenamos stdout para que piper no se bloquee con el pipe
            # lleno y dejamos que say() termine normal. Sin este guard, cada
            # comando spameaba un traceback y mataba a piper a mitad de síntesis.
            logger.warning("tts_no_output_device err=%s", e)
            stdout.read()
            return False
        cancelled = False
        try:
            while True:
                if self._cancel.is_set():
                    cancelled = True
                    break
                chunk = stdout.read(READ_CHUNK)
                if not chunk:
                    break
                if volume != 1.0:
                    chunk = _apply_gain(chunk, volume)
                stream.write(chunk)
        finally:
            try:
                stream.stop(ignore_errors=True)
            except TypeError:
                stream.stop()
            try:
                stream.close()
            except Exception:
                pass
        return cancelled

    def cancel(self) -> None:
        """Idempotente. Setea el flag y mata el subprocess; el `say()` retorna inmediatamente."""
        self._cancel.set()
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                except Exception:
                    logger.exception("tts_cancel_terminate_failed")

    def shutdown(self) -> None:
        self.cancel()


def _apply_gain(pcm_chunk: bytes, volume: float) -> bytes:
    """Aplica gain lineal a int16 PCM. volume==1.0 → identidad (no se llama)."""
    import numpy as np

    arr = np.frombuffer(pcm_chunk, dtype=np.int16).astype(np.float32) * volume
    np.clip(arr, -32768, 32767, out=arr)
    return arr.astype(np.int16).tobytes()
