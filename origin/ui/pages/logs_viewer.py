"""Visor de logs en vivo. Tail incremental con QTimer + filtros simples."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...engine.paths import default_paths
from ..i18n.tr import register_retranslatable, tr

logger = logging.getLogger(__name__)

LEVELS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]
LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "ALL": -1}


class LogsViewerPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log_path: Path = default_paths().log_file
        self._read_offset: int = 0
        self._buffer: list[str] = []
        self._max_lines = 5000
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        register_retranslatable(self.retranslate)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self._lbl_level = QLabel()
        self._cb_level = QComboBox()
        for l in LEVELS:
            self._cb_level.addItem(l, l)
        self._cb_level.currentIndexChanged.connect(self._refresh)
        self._lbl_search = QLabel()
        self._inp_search = QLineEdit()
        self._inp_search.textChanged.connect(self._refresh)
        self._btn_copy = QPushButton()
        self._btn_copy.clicked.connect(self._copy_all)
        self._btn_clear = QPushButton()
        self._btn_clear.clicked.connect(self._clear_view)
        self._btn_open = QPushButton()
        self._btn_open.clicked.connect(self._open_folder)
        bar.addWidget(self._lbl_level)
        bar.addWidget(self._cb_level)
        bar.addWidget(self._lbl_search)
        bar.addWidget(self._inp_search, 1)
        bar.addWidget(self._btn_copy)
        bar.addWidget(self._btn_clear)
        bar.addWidget(self._btn_open)
        root.addLayout(bar)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(self._max_lines)
        root.addWidget(self._text, 1)

        self.retranslate()

    def _tick(self) -> None:
        if not self._log_path.exists():
            return
        try:
            size = self._log_path.stat().st_size
            if size < self._read_offset:
                # rotación → empezar de cero
                self._read_offset = 0
            if size == self._read_offset:
                return
            with self._log_path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self._read_offset)
                chunk = f.read()
                self._read_offset = f.tell()
        except Exception:
            logger.exception("logs_tail_failed")
            return
        if not chunk:
            return
        for line in chunk.splitlines():
            self._buffer.append(line)
        if len(self._buffer) > self._max_lines:
            self._buffer = self._buffer[-self._max_lines:]
        self._refresh()

    def _refresh(self) -> None:
        wanted_level = self._cb_level.currentData() or "ALL"
        query = self._inp_search.text().strip().lower()
        out: list[str] = []
        min_rank = LEVEL_RANK.get(wanted_level, -1)
        for line in self._buffer:
            if min_rank >= 0:
                # nuestro formato pretty incluye el level como ' DEBUG ' / ' INFO ' / etc.
                line_rank = -1
                for lvl, rank in LEVEL_RANK.items():
                    if lvl != "ALL" and f" {lvl[:7].ljust(7)}" in line:
                        line_rank = rank
                        break
                if line_rank < min_rank:
                    continue
            if query and query not in line.lower():
                continue
            out.append(line)
        self._text.setPlainText("\n".join(out))

    def _copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self._text.toPlainText())

    def _clear_view(self) -> None:
        self._buffer.clear()
        self._text.clear()

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_path.parent)))

    def retranslate(self) -> None:
        self._lbl_level.setText(tr("logs.filter_level"))
        self._lbl_search.setText(tr("logs.search"))
        self._btn_copy.setText(tr("logs.copy_all"))
        self._btn_clear.setText(tr("logs.clear_view"))
        self._btn_open.setText(tr("logs.open_folder"))
