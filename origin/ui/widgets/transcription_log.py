"""Lista circular de las últimas N transcripciones con su match (color-coded)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem


@dataclass(frozen=True)
class Entry:
    when: str           # HH:MM:SS
    lang: str           # "ES" / "EN"
    text: str
    command_id: str | None
    score: float
    elapsed_ms: int
    dry_run: bool


class TranscriptionLog(QListWidget):
    def __init__(self, capacity: int = 10) -> None:
        super().__init__()
        self._capacity = capacity
        self._entries: deque[Entry] = deque(maxlen=capacity)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QListWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)

    def add(self, entry: Entry) -> None:
        self._entries.append(entry)
        self._render()

    def clear_all(self) -> None:
        self._entries.clear()
        self._render()

    def _render(self) -> None:
        self.clear()
        for e in self._entries:
            cmd = e.command_id or "—"
            line = f"{e.when}  [{e.lang}]  {e.text!r}  →  {cmd}  ({e.score:.0f}, {e.elapsed_ms}ms)"
            item = QListWidgetItem(line)
            if e.dry_run:
                item.setForeground(QColor(150, 150, 160))
            elif e.command_id:
                item.setForeground(QColor(60, 160, 80))
            else:
                item.setForeground(QColor(190, 80, 80))
            self.addItem(item)


def now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")
