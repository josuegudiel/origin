"""QLineEdit readonly que en focus captura el próximo keyPressEvent y muestra el nombre.

Devuelve nombres compatibles con `engine.runtime.Orchestrator._parse_pynput_key`:
letras/dígitos (1 char) o nombres especiales (`f1`..`f24`, `enter`, `space`, etc.).
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QLineEdit

_QT_KEY_TO_NAME: dict[int, str] = {
    Qt.Key_F1: "f1", Qt.Key_F2: "f2", Qt.Key_F3: "f3", Qt.Key_F4: "f4",
    Qt.Key_F5: "f5", Qt.Key_F6: "f6", Qt.Key_F7: "f7", Qt.Key_F8: "f8",
    Qt.Key_F9: "f9", Qt.Key_F10: "f10", Qt.Key_F11: "f11", Qt.Key_F12: "f12",
    Qt.Key_F13: "f13", Qt.Key_F14: "f14", Qt.Key_F15: "f15", Qt.Key_F16: "f16",
    Qt.Key_Escape: "esc",
    Qt.Key_Tab: "tab",
    Qt.Key_Space: "space",
    Qt.Key_Return: "enter",
    Qt.Key_Enter: "enter",
    Qt.Key_Backspace: "backspace",
    Qt.Key_Delete: "delete",
    Qt.Key_Insert: "insert",
    Qt.Key_Home: "home",
    Qt.Key_End: "end",
    Qt.Key_PageUp: "pageup",
    Qt.Key_PageDown: "pagedown",
    Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
    Qt.Key_CapsLock: "capslock",
    Qt.Key_NumLock: "numlock",
    Qt.Key_ScrollLock: "scrolllock",
}


def qt_to_keyname(qt_key: int, text: str = "") -> str | None:
    if qt_key in _QT_KEY_TO_NAME:
        return _QT_KEY_TO_NAME[qt_key]
    # letras y dígitos
    if Qt.Key_A <= qt_key <= Qt.Key_Z:
        return chr(qt_key).lower()
    if Qt.Key_0 <= qt_key <= Qt.Key_9:
        return chr(qt_key)
    if text and len(text) == 1 and text.isalnum():
        return text.lower()
    return None


class KeyCapture(QLineEdit):
    """Lee la próxima tecla que el usuario presione mientras tiene foco."""

    keyCaptured = Signal(str)

    def __init__(
        self,
        initial: str = "",
        capture_combo: bool = False,
        validate_cb: Callable[[str], str | None] | None = None,
        parent: object | None = None,
    ) -> None:
        super().__init__(initial, parent)
        self.setReadOnly(True)
        self.setPlaceholderText("…")
        self._capture_combo = capture_combo
        self._validate_cb = validate_cb
        self._waiting = False
        self.setStyleSheet("QLineEdit:focus { border: 2px solid #6080ff; }")

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._waiting = True
        self.setText("⌛ " + self.text())

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if self._waiting and self.text().startswith("⌛ "):
            self.setText(self.text()[2:])
        self._waiting = False

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._waiting:
            return super().keyPressEvent(event)
        if event.key() in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            # Modificador puro: ignorar en captura simple; en combo, esperar el final.
            return
        name = qt_to_keyname(event.key(), event.text())
        if name is None:
            return
        if self._capture_combo:
            mods = []
            m = event.modifiers()
            if m & Qt.ControlModifier:
                mods.append("ctrl")
            if m & Qt.ShiftModifier:
                mods.append("shift")
            if m & Qt.AltModifier:
                mods.append("alt")
            if m & Qt.MetaModifier:
                mods.append("win")
            value = "+".join([*mods, name])
        else:
            value = name
        if self._validate_cb:
            err = self._validate_cb(value)
            if err:
                self.setText(f"⚠ {value} ({err})")
                self._waiting = False
                self.clearFocus()
                return
        self.setText(value)
        self.keyCaptured.emit(value)
        self._waiting = False
        self.clearFocus()
