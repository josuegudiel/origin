"""Tema light/dark/system. Aplica QSS al QApplication según preferencia.

Usa `QStyleHints.colorScheme()` (Qt 6.5+) cuando theme='system' para seguir al SO.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _qss_for(scheme: str) -> str:
    path = _ASSETS_DIR / ("style_dark.qss" if scheme == "dark" else "style_light.qss")
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def resolve_scheme(theme: str) -> str:
    """`theme` ∈ {system, light, dark} → 'light'|'dark'."""
    if theme in ("light", "dark"):
        return theme
    hints = QGuiApplication.styleHints()
    try:
        cs = hints.colorScheme()
        if cs == Qt.ColorScheme.Dark:
            return "dark"
        if cs == Qt.ColorScheme.Light:
            return "light"
    except Exception:
        pass
    return "light"


def apply_theme(app, theme: str) -> None:
    scheme = resolve_scheme(theme)
    app.setStyleSheet(_qss_for(scheme))
