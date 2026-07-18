"""Wrapper de faster-whisper con load perezoso, warm-up y downgrade CUDA→CPU."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np

from .paths import bundled_resource_dir

logger = logging.getLogger(__name__)


def _bundled_models_dir() -> Path | None:
    """Carpeta de modelos pre-descargados dentro del bundle PyInstaller."""
    if not getattr(sys, "frozen", False):
        return None
    candidate = bundled_resource_dir() / "models"
    return candidate if candidate.exists() else None


def detect_device(preference: str) -> str:
    """`auto` → cuda si está disponible, sino cpu. `cpu`/`cuda` → respetar literal."""
    if preference == "cpu":
        return "cpu"
    if preference == "cuda":
        return "cuda"
    try:
        import ctranslate2  # type: ignore[import-untyped]

        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except Exception:
        return "cpu"


def auto_compute_type(device: str, requested: str) -> str:
    if requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


class Transcriber:
    """Cargador y transcriptor reutilizable. NO thread-safe entre transcribe() concurrentes;
    usar un solo worker (ver runtime.py).
    """

    def __init__(
        self,
        model_name: str,
        device_preference: str = "auto",
        compute_type: str = "auto",
        download_root: Path | None = None,
    ) -> None:
        self._model_name = model_name
        self._device_pref = device_preference
        self._compute_pref = compute_type
        self._download_root = download_root or _bundled_models_dir()
        self._model: Any | None = None
        self._device: str | None = None
        self._compute: str | None = None
        self._lock = threading.Lock()

    @property
    def device(self) -> str | None:
        return self._device

    @property
    def compute_type(self) -> str | None:
        return self._compute

    def load(self) -> None:
        """Carga el modelo (idempotente). Llamar antes del primer transcribe para evitar
        latencia en el primer PTT real."""
        with self._lock:
            if self._model is not None:
                return
            self._open(self._device_pref, self._compute_pref)
            self._warm_up()

    def _open(self, device_pref: str, compute_pref: str) -> None:
        from faster_whisper import WhisperModel  # lazy

        device = detect_device(device_pref)
        compute = auto_compute_type(device, compute_pref)
        kwargs: dict[str, Any] = {"device": device, "compute_type": compute}
        if self._download_root:
            kwargs["download_root"] = str(self._download_root)
        logger.info(
            "stt_loading model=%s device=%s compute=%s download_root=%s",
            self._model_name, device, compute, kwargs.get("download_root"),
        )
        self._model = WhisperModel(self._model_name, **kwargs)
        self._device = device
        self._compute = compute

    def _warm_up(self) -> None:
        # 1s de silencio sintético — fuerza al runtime a JIT-compilar el grafo.
        silence = np.zeros(16000, dtype=np.float32)
        try:
            list(
                self._model.transcribe(  # type: ignore[union-attr]
                    silence, language="es", beam_size=1, vad_filter=False
                )[0]
            )
        except Exception:
            logger.exception("stt_warmup_failed")

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        """Devuelve texto concatenado. Vacío si Whisper no detectó habla."""
        if self._model is None:
            self.load()
        assert self._model is not None
        try:
            return self._do_transcribe(audio, language)
        except RuntimeError as e:
            if self._device == "cuda" and "cuda" in str(e).lower():
                logger.warning("cuda_failed_downgrading_to_cpu err=%r", e)
                self._downgrade_to_cpu()
                return self._do_transcribe(audio, language)
            raise

    def _do_transcribe(self, audio: np.ndarray, language: str) -> str:
        assert self._model is not None
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def _downgrade_to_cpu(self) -> None:
        with self._lock:
            self._model = None
            self._open("cpu", "int8")
            # Sin warm-up adicional — el CPU es rápido en silencio, y la transcripción
            # del audio actual sigue inmediatamente.
