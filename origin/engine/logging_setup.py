"""Logging estructurado opcional (pretty | json). RotatingFileHandler 5MB x 3."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal

LogFormat = Literal["pretty", "json"]


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            base.update(extra)
        return json.dumps(base, ensure_ascii=False)


_NOISY_LOGGERS = (
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "faster_whisper",
    "ctranslate2",
    "watchdog",
    "watchdog.observers",
    "sounddevice",
    "PIL",  # via QPixmap save por si acaso
)


def setup(level: str, log_file: Path | None, fmt: LogFormat = "pretty") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    # Limpieza para reconfigurar sobre reload.
    for h in list(root.handlers):
        root.removeHandler(h)
    # Silenciar librerías ruidosas — con `--log-level DEBUG` el usuario quiere
    # debug de Origin, no de pynput tickleando cada keystroke ni de ctranslate2.
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    if fmt == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
