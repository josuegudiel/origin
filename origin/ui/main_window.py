"""Ventana principal: sidebar + header + QStackedWidget + banner de avisos."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..engine.runtime import Orchestrator
from .engine_bridge import EngineBridge
from .i18n.tr import register_retranslatable, tr
from .pages.about import AboutPage
from .pages.commands_editor import CommandsEditorPage
from .pages.dashboard import DashboardPage
from .pages.headtrack import HeadTrackPage
from .pages.logs_viewer import LogsViewerPage
from .pages.profiles_manager import ProfilesManagerPage
from .pages.settings import SettingsPage

logger = logging.getLogger(__name__)


SIDEBAR = [
    ("dashboard", "sidebar.dashboard"),
    ("commands", "sidebar.commands"),
    ("profiles", "sidebar.profiles"),
    ("headtrack", "sidebar.headtrack"),
    ("settings", "sidebar.settings"),
    ("logs", "sidebar.logs"),
    ("about", "sidebar.about"),
]


class MainWindow(QWidget):
    def __init__(
        self,
        orch: Orchestrator,
        bridge: EngineBridge,
        on_close_to_tray: callable | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._orch = orch
        self._bridge = bridge
        self._on_close_to_tray = on_close_to_tray
        self.resize(1100, 720)
        self.setWindowTitle("Origin")
        self._build_ui()
        self._wire()
        register_retranslatable(self.retranslate)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ---- Header ----
        header = QWidget()
        header.setStyleSheet("background: palette(window);")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 8, 12, 8)
        self._state_dot = QLabel("●")
        self._state_dot.setObjectName("StatusDot")
        self._state_dot.setProperty("state", "loading_model")
        self._state_dot.setStyleSheet("font-size: 16pt;")
        self._state_text = QLabel()
        self._state_text.setStyleSheet("font-weight: 600;")
        h.addWidget(self._state_dot)
        h.addWidget(self._state_text)
        h.addStretch(1)

        self._lang_btn_es = QPushButton("ES")
        self._lang_btn_en = QPushButton("EN")
        self._lang_btn_es.setCheckable(True)
        self._lang_btn_en.setCheckable(True)
        self._lang_btn_es.setFixedWidth(40)
        self._lang_btn_en.setFixedWidth(40)
        self._lang_btn_es.clicked.connect(lambda: self._on_lang_clicked("es"))
        self._lang_btn_en.clicked.connect(lambda: self._on_lang_clicked("en"))
        h.addWidget(self._lang_btn_es)
        h.addWidget(self._lang_btn_en)

        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(180)
        self._profile_combo.currentIndexChanged.connect(self._on_header_profile_changed)
        h.addWidget(self._profile_combo)

        self._pause_btn = QPushButton()
        self._pause_btn.clicked.connect(self._on_pause_clicked)
        h.addWidget(self._pause_btn)

        root.addWidget(header)

        # ---- Banner ----
        self._banner = QLabel("")
        self._banner.setObjectName("Banner")
        self._banner.setProperty("kind", "info")
        self._banner.setVisible(False)
        self._banner.setWordWrap(True)
        root.addWidget(self._banner)

        # ---- Body: sidebar + stacked ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        root.addLayout(body, 1)

        self._sidebar = QListWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(180)
        self._sidebar.currentRowChanged.connect(self._on_sidebar_changed)
        for key, _label_key in SIDEBAR:
            item = QListWidgetItem("")
            item.setData(Qt.UserRole, key)
            self._sidebar.addItem(item)
        body.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {
            "headtrack": HeadTrackPage(self._orch, self._bridge),
            "dashboard": DashboardPage(self._orch, self._bridge),
            "commands": CommandsEditorPage(self._orch, self._bridge),
            "profiles": ProfilesManagerPage(self._orch, self._bridge),
            "settings": SettingsPage(self._orch, self._bridge),
            "logs": LogsViewerPage(),
            "about": AboutPage(),
        }
        for key, _ in SIDEBAR:
            self._stack.addWidget(self._pages[key])
        body.addWidget(self._stack, 1)

        self._sidebar.setCurrentRow(0)
        self._reload_profile_combo()
        self.retranslate()
        self._refresh_state(self._orch.state.value)

    def _wire(self) -> None:
        self._bridge.engine_state.connect(self._refresh_state)
        self._bridge.language_changed.connect(self._on_external_lang)
        self._bridge.profile_changed.connect(self._on_external_profile)
        self._bridge.config_reloaded.connect(self._on_config_reloaded)
        self._bridge.config_error.connect(self._on_config_error)

    # --------------------------------------------------------- header slots

    def _refresh_state(self, state: str) -> None:
        self._state_dot.setProperty("state", state)
        self._state_dot.style().unpolish(self._state_dot)
        self._state_dot.style().polish(self._state_dot)
        self._state_text.setText(tr(f"state.{state}") if state else "")
        is_paused = state == "paused"
        self._pause_btn.setText(tr("header.resume") if is_paused else tr("header.pause"))

    def _on_pause_clicked(self) -> None:
        if self._orch.is_paused():
            self._orch.resume()
        else:
            self._orch.pause()

    def _on_lang_clicked(self, lang: str) -> None:
        self._orch.set_active_language(lang)
        self._sync_lang_buttons(lang)

    def _sync_lang_buttons(self, lang: str) -> None:
        self._lang_btn_es.setChecked(lang == "es")
        self._lang_btn_en.setChecked(lang == "en")

    def _on_external_lang(self, lang: str) -> None:
        self._sync_lang_buttons(lang)

    def _on_header_profile_changed(self, idx: int) -> None:
        pid = self._profile_combo.itemData(idx)
        if pid and pid != self._orch.profiles.active_id:
            self._orch.set_active_profile(pid)

    def _on_external_profile(self, pid: str) -> None:
        idx = self._profile_combo.findData(pid)
        if idx >= 0 and self._profile_combo.currentIndex() != idx:
            self._profile_combo.blockSignals(True)
            self._profile_combo.setCurrentIndex(idx)
            self._profile_combo.blockSignals(False)

    def _on_config_reloaded(self) -> None:
        self._reload_profile_combo()
        self._show_banner("info", tr("banner.config_reloaded"))

    def _on_config_error(self, err: str) -> None:
        self._show_banner("error", tr("banner.config_error", error=err))

    def _show_banner(self, kind: str, msg: str, autohide_ms: int = 4000) -> None:
        self._banner.setProperty("kind", kind)
        self._banner.style().unpolish(self._banner)
        self._banner.style().polish(self._banner)
        self._banner.setText(msg)
        self._banner.setVisible(True)
        if autohide_ms and kind != "error":
            from PySide6.QtCore import QTimer

            QTimer.singleShot(autohide_ms, lambda: self._banner.setVisible(False))

    def _reload_profile_combo(self) -> None:
        self._profile_combo.blockSignals(True)
        try:
            self._profile_combo.clear()
            ui_lang = self._orch.config.settings.ui_language
            for p in self._orch.config.profiles:
                label = p.label_for(ui_lang)
                self._profile_combo.addItem(label, p.id)
            idx = self._profile_combo.findData(self._orch.profiles.active_id)
            if idx >= 0:
                self._profile_combo.setCurrentIndex(idx)
            self._sync_lang_buttons(self._orch.config.settings.active_language)
        finally:
            self._profile_combo.blockSignals(False)

    def _on_sidebar_changed(self, row: int) -> None:
        self._stack.setCurrentIndex(row)

    def navigate_to(self, key: str) -> None:
        for i, (k, _) in enumerate(SIDEBAR):
            if k == key:
                self._sidebar.setCurrentRow(i)
                break

    # --------------------------------------------------------- close

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._on_close_to_tray is not None:
            event.ignore()
            self.hide()
            try:
                self._on_close_to_tray()
            except Exception:
                logger.exception("close_to_tray_failed")
            return
        super().closeEvent(event)

    # --------------------------------------------------------- i18n

    def retranslate(self) -> None:
        for i, (_key, label_key) in enumerate(SIDEBAR):
            self._sidebar.item(i).setText(tr(label_key))
        is_paused = self._orch.is_paused()
        self._pause_btn.setText(tr("header.resume") if is_paused else tr("header.pause"))
        self._refresh_state(self._orch.state.value)
        # Rebuild profile combo (labels dependen del ui_language).
        self._reload_profile_combo()
