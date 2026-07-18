"""Test del widget KeyCapture en Settings."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.mark.gui
def test_key_capture_emits_keyname(qtbot):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication

    from origin.ui.widgets.key_capture import KeyCapture

    w = KeyCapture(initial="f12", capture_combo=False)
    qtbot.addWidget(w)
    captured: list[str] = []
    w.keyCaptured.connect(captured.append)
    # Sin show() en offscreen: posteamos el QKeyEvent directamente al widget.
    w._waiting = True  # noqa: SLF001
    QApplication.sendEvent(
        w,
        QKeyEvent(QEvent.KeyPress, Qt.Key_F11, Qt.NoModifier, "f11"),
    )
    assert captured == ["f11"]
    assert w.text() == "f11"


@pytest.mark.gui
def test_key_capture_combo_with_modifiers(qtbot):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication

    from origin.ui.widgets.key_capture import KeyCapture

    w = KeyCapture(initial="ctrl+f12", capture_combo=True)
    qtbot.addWidget(w)
    captured: list[str] = []
    w.keyCaptured.connect(captured.append)
    w._waiting = True  # noqa: SLF001
    QApplication.sendEvent(
        w,
        QKeyEvent(QEvent.KeyPress, Qt.Key_F10, Qt.ControlModifier, ""),
    )
    assert captured == ["ctrl+f10"]
