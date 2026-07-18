"""Página Dashboard: estado, VU meter, últimas transcripciones, latencias, Pause/Resume."""
from __future__ import annotations

from collections import deque
from typing import Any

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...engine.runtime import Orchestrator
from ..engine_bridge import EngineBridge
from ..i18n.tr import register_retranslatable, tr
from ..widgets.transcription_log import Entry, TranscriptionLog, now_hms
from ..widgets.vu_meter import VuMeter


class DashboardPage(QWidget):
    def __init__(self, orch: Orchestrator, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._orch = orch
        self._bridge = bridge
        self._stt_window: deque[int] = deque(maxlen=10)
        self._match_window: deque[int] = deque(maxlen=10)
        self._last_text: str = ""
        self._last_lang: str = "es"
        self._last_stt_ms: int = 0
        self._build_ui()
        self._wire()
        register_retranslatable(self.retranslate)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Engine state
        self._state_box = QGroupBox()
        sv = QVBoxLayout(self._state_box)
        row = QHBoxLayout()
        self._state_dot = QLabel("●")
        self._state_dot.setObjectName("StatusDot")
        self._state_dot.setProperty("state", "loading_model")
        self._state_dot.setStyleSheet("font-size: 18pt;")
        self._state_label = QLabel()
        self._state_label.setStyleSheet("font-size: 12pt; font-weight: 600;")
        row.addWidget(self._state_dot)
        row.addWidget(self._state_label, 1)
        sv.addLayout(row)
        self._pause_btn = QPushButton()
        self._pause_btn.clicked.connect(self._toggle_pause)
        sv.addWidget(self._pause_btn)

        # Mic VU
        self._vu_box = QGroupBox()
        vv = QVBoxLayout(self._vu_box)
        self._vu = VuMeter()
        vv.addWidget(self._vu)

        # Latency
        self._lat_box = QGroupBox()
        lv = QGridLayout(self._lat_box)
        self._lbl_stt_caption = QLabel()
        self._lbl_match_caption = QLabel()
        self._lbl_total_caption = QLabel()
        self._lbl_stt_val = QLabel("— ms")
        self._lbl_match_val = QLabel("— ms")
        self._lbl_total_val = QLabel("— ms")
        for lbl in (self._lbl_stt_val, self._lbl_match_val, self._lbl_total_val):
            lbl.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lv.addWidget(self._lbl_stt_caption, 0, 0)
        lv.addWidget(self._lbl_stt_val, 1, 0)
        lv.addWidget(self._lbl_match_caption, 0, 1)
        lv.addWidget(self._lbl_match_val, 1, 1)
        lv.addWidget(self._lbl_total_caption, 0, 2)
        lv.addWidget(self._lbl_total_val, 1, 2)

        # Recent transcriptions
        self._recent_box = QGroupBox()
        rv = QVBoxLayout(self._recent_box)
        self._log = TranscriptionLog(capacity=10)
        rv.addWidget(self._log)

        grid.addWidget(self._state_box, 0, 0)
        grid.addWidget(self._vu_box, 0, 1)
        grid.addWidget(self._lat_box, 1, 0, 1, 2)
        grid.addWidget(self._recent_box, 2, 0, 1, 2)
        grid.setRowStretch(2, 1)
        root.addLayout(grid)

        self.retranslate()
        self._refresh_state(self._orch.state.value)

    def _wire(self) -> None:
        self._bridge.engine_state.connect(self._refresh_state)
        self._bridge.audio_level.connect(self._vu.set_level)
        self._bridge.transcription_done.connect(self._on_transcription)
        self._bridge.match_done.connect(self._on_match)

    # ------------------------------------------------------------------ Slots

    def _refresh_state(self, state: str) -> None:
        self._state_dot.setProperty("state", state)
        self._state_dot.style().unpolish(self._state_dot)
        self._state_dot.style().polish(self._state_dot)
        self._state_label.setText(tr(f"state.{state}") if state else tr("state.ready"))
        is_paused = state == "paused"
        self._pause_btn.setText(tr("header.resume") if is_paused else tr("header.pause"))

    def _toggle_pause(self) -> None:
        if self._orch.is_paused():
            self._orch.resume()
        else:
            self._orch.pause()

    def _on_transcription(self, p: dict[str, Any]) -> None:
        self._last_text = p.get("text", "")
        self._last_lang = p.get("language", "es")
        self._last_stt_ms = int(p.get("elapsed_ms", 0))
        self._stt_window.append(self._last_stt_ms)
        self._update_latency()

    def _on_match(self, p: dict[str, Any]) -> None:
        match_ms = int(p.get("elapsed_ms", 0))
        self._match_window.append(match_ms)
        self._update_latency()
        entry = Entry(
            when=now_hms(),
            lang=(self._last_lang or "es").upper(),
            text=self._last_text,
            command_id=p.get("command_id"),
            score=float(p.get("score", 0.0)),
            elapsed_ms=self._last_stt_ms + match_ms,
            dry_run=False,
        )
        self._log.add(entry)

    def _update_latency(self) -> None:
        avg = lambda d: int(sum(d) / len(d)) if d else None
        stt_avg = avg(self._stt_window)
        match_avg = avg(self._match_window)
        total = (stt_avg or 0) + (match_avg or 0) if (stt_avg or match_avg) else None
        self._lbl_stt_val.setText(f"{stt_avg} ms" if stt_avg is not None else "— ms")
        self._lbl_match_val.setText(f"{match_avg} ms" if match_avg is not None else "— ms")
        self._lbl_total_val.setText(f"{total} ms" if total is not None else "— ms")

    # ------------------------------------------------------------------ i18n

    def retranslate(self) -> None:
        self._state_box.setTitle(tr("dashboard.engine_state"))
        self._vu_box.setTitle(tr("dashboard.mic_level"))
        self._lat_box.setTitle(tr("dashboard.latency"))
        self._recent_box.setTitle(tr("dashboard.recent"))
        self._lbl_stt_caption.setText(tr("dashboard.latency.stt"))
        self._lbl_match_caption.setText(tr("dashboard.latency.match"))
        self._lbl_total_caption.setText(tr("dashboard.latency.total"))
        is_paused = self._orch.is_paused()
        self._pause_btn.setText(tr("header.resume") if is_paused else tr("header.pause"))
