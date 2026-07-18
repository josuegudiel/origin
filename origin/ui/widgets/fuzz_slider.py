"""Slider 0–100 con preview en vivo: el usuario tipea una frase, ve top-N matches."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class FuzzSlider(QWidget):
    valueChanged = Signal(int)

    def __init__(
        self,
        initial: int,
        preview_cb: Callable[[str], list[tuple[str, float]]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preview_cb = preview_cb

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(initial)
        self._label = QLabel(str(initial))
        self._label.setMinimumWidth(36)
        row.addWidget(self._slider, 1)
        row.addWidget(self._label)
        v.addLayout(row)

        self._preview_input = QLineEdit()
        v.addWidget(self._preview_input)
        self._preview_list = QListWidget()
        self._preview_list.setMaximumHeight(140)
        v.addWidget(self._preview_list)

        self._slider.valueChanged.connect(self._on_value_changed)
        self._preview_input.textChanged.connect(self._refresh_preview)

    @property
    def threshold(self) -> int:
        return self._slider.value()

    def setPlaceholder(self, text: str) -> None:  # noqa: N802
        self._preview_input.setPlaceholderText(text)

    def setPreviewCallback(self, cb: Callable[[str], list[tuple[str, float]]]) -> None:  # noqa: N802
        self._preview_cb = cb
        self._refresh_preview()

    def _on_value_changed(self, v: int) -> None:
        self._label.setText(str(v))
        self._refresh_preview()
        self.valueChanged.emit(v)

    def _refresh_preview(self) -> None:
        self._preview_list.clear()
        if not self._preview_cb:
            return
        text = self._preview_input.text().strip()
        if not text:
            return
        try:
            results = self._preview_cb(text)
        except Exception:
            return
        thr = self.threshold
        for label, score in results:
            item = QListWidgetItem(f"{score:5.1f}   {label}")
            if score >= thr:
                item.setForeground(Qt.darkGreen)
            else:
                item.setForeground(Qt.gray)
            self._preview_list.addItem(item)
