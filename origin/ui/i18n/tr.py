"""Helper de traducción. `tr("key")` mira el dict activo; fallback a ES; última opción la key raw.

Las páginas registran sus widgets via `register_retranslatable(callback)` para repintar
sus labels cuando cambia el idioma de la UI.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ...engine.i18n_loader import load_strings

_I18N_DIR = Path(__file__).resolve().parent
_current_lang = "es"
_dict_active: dict[str, str] = {}
_dict_fallback: dict[str, str] = {}
_retranslatables: list[Callable[[], None]] = []


def load(lang: str) -> None:
    global _current_lang, _dict_active, _dict_fallback
    _current_lang = lang
    _dict_active = load_strings(_I18N_DIR, lang)
    _dict_fallback = load_strings(_I18N_DIR, "es") if lang != "es" else {}


def current() -> str:
    return _current_lang


def tr(key: str, **fmt: object) -> str:
    raw = _dict_active.get(key) or _dict_fallback.get(key) or key
    if fmt:
        try:
            return raw.format(**fmt)
        except (KeyError, IndexError):
            return raw
    return raw


def register_retranslatable(callback: Callable[[], None]) -> None:
    _retranslatables.append(callback)


def retranslate_all() -> None:
    for cb in list(_retranslatables):
        try:
            cb()
        except Exception:
            import logging

            logging.getLogger(__name__).exception("retranslate_failed")


# Carga ES por defecto al import — el resto se aplica desde Settings/MainWindow.
load("es")
