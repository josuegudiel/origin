"""Captura de audio con `sounddevice`. Stream siempre abierto; el recorder marca
ventanas de captura (PTT-down → PTT-up) y devuelve el `np.ndarray` 16kHz mono float32.

RMS por callback → función `on_level` para alimentar el VU meter de la UI.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def list_input_devices() -> list[dict[str, Any]]:
    """`[{"index": int, "name": str, "channels": int, "default": bool}, ...]`."""
    import sounddevice as sd  # lazy

    try:
        default_input = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else None
    except Exception:
        default_input = None
    devices = sd.query_devices()
    out: list[dict[str, Any]] = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            out.append(
                {
                    "index": i,
                    "name": d["name"],
                    "channels": d["max_input_channels"],
                    "default": (default_input is not None and i == default_input),
                }
            )
    return out


class Recorder:
    """Audio capture continuo. `begin_capture()` arma una ventana; `end_capture()` la cierra."""

    def __init__(
        self,
        sample_rate: int = 16000,
        mic_device: int | None = None,
        max_record_seconds: int = 8,
        on_level: Callable[[float], None] | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._mic_device = mic_device
        self._max_samples = sample_rate * max_record_seconds
        self._on_level = on_level
        self._capturing = False
        self._buffer: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: Any | None = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def start_stream(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd  # lazy

        blocksize = int(self._sample_rate * 0.03)  # ~30ms blocks → ~33Hz RMS rate

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            if status:
                logger.debug("audio_status %s", status)
            mono = indata[:, 0] if indata.ndim > 1 else indata
            if mono.size > 0 and self._on_level is not None:
                rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))
                try:
                    self._on_level(rms)
                except Exception:
                    logger.exception("on_level_callback_failed")
            with self._lock:
                if self._capturing:
                    self._buffer.append(mono.astype(np.float32, copy=True))

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            device=self._mic_device,
            callback=callback,
        )
        self._stream.start()
        logger.info(
            "audio_stream_started rate=%d device=%s blocksize=%d",
            self._sample_rate, self._mic_device, blocksize,
        )

    def stop_stream(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            logger.exception("audio_stream_stop_failed")
        finally:
            self._stream = None
            logger.info("audio_stream_stopped")

    def restart_stream(self, mic_device: int | None) -> None:
        """Cierra y reabre con un nuevo device (cambio de mic desde Settings).

        Importante: si había una captura en vuelo, se descarta — sin esto, el
        audio del mic viejo + el del nuevo se concatenaban en el mismo buffer.
        """
        with self._lock:
            self._capturing = False
            self._buffer = []
        self.stop_stream()
        self._mic_device = mic_device
        self.start_stream()

    def begin_capture(self) -> None:
        with self._lock:
            self._buffer = []
            self._capturing = True

    def end_capture(self) -> np.ndarray:
        with self._lock:
            self._capturing = False
            chunks = self._buffer
            self._buffer = []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(chunks)
        if audio.shape[0] > self._max_samples:
            # Truncamos a max_record_seconds — el usuario debe enterarse para
            # no asumir que su frase larga se procesó completa.
            logger.warning(
                "audio_truncated samples=%d max=%d (dur=%.1fs)",
                audio.shape[0], self._max_samples,
                audio.shape[0] / self._sample_rate,
            )
            audio = audio[: self._max_samples]
        return audio

    def is_capturing(self) -> bool:
        with self._lock:
            return self._capturing
