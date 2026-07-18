"""System tray icon + menú dinámico (perfil/idioma/estado se reflejan en vivo)."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..engine.runtime import Orchestrator
from .engine_bridge import EngineBridge
from .i18n.tr import tr

logger = logging.getLogger(__name__)


def _make_icon(state: str) -> QIcon:
    """Icono programático (sin assets) coloreado según estado."""
    px = QPixmap(64, 64)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    color = {
        "paused": QColor(128, 128, 128),
        "loading_model": QColor(100, 130, 230),
        "recording": QColor(220, 180, 50),
        "transcribing": QColor(220, 180, 50),
        "executing": QColor(220, 180, 50),
        "error": QColor(200, 70, 70),
    }.get(state, QColor(50, 160, 80))  # default = ready
    p.setBrush(color)
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 60, 60)
    p.setPen(Qt.white)
    p.setFont(QFont("Arial", 36, QFont.Bold))
    p.drawText(px.rect(), Qt.AlignCenter, "O")
    p.end()
    return QIcon(px)


class OriginTray(QSystemTrayIcon):
    def __init__(
        self,
        orch: Orchestrator,
        bridge: EngineBridge,
        on_show_dashboard: Callable[[], None],
        on_quit: Callable[[], None],
        on_open_settings: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._orch = orch
        self._bridge = bridge
        self._on_show = on_show_dashboard
        self._on_quit = on_quit
        self._on_settings = on_open_settings or on_show_dashboard
        self._current_state = "loading_model"

        self.setIcon(_make_icon(self._current_state))
        self._menu = QMenu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self._rebuild_menu()
        self._update_tooltip()

        bridge.engine_state.connect(self._on_state)
        bridge.profile_changed.connect(lambda _id: self._rebuild_menu())
        bridge.language_changed.connect(lambda _l: self._rebuild_menu())
        bridge.config_reloaded.connect(self._rebuild_menu)

    @staticmethod
    def is_available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    # ---------- menú ----------

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        act_show = QAction(tr("tray.show_dashboard"), self._menu)
        act_show.triggered.connect(self._on_show)
        self._menu.addAction(act_show)
        self._menu.addSeparator()

        pause_label = tr("tray.resume") if self._orch.is_paused() else tr("tray.pause")
        act_pause = QAction(pause_label, self._menu)
        act_pause.triggered.connect(self._toggle_pause)
        self._menu.addAction(act_pause)

        # Perfiles
        prof_menu = self._menu.addMenu(tr("tray.switch_profile"))
        prof_group = QActionGroup(prof_menu)
        prof_group.setExclusive(True)
        active_pid = self._orch.profiles.active_id
        for p in self._orch.config.profiles:
            label = p.label_es if self._orch.config.settings.ui_language == "es" else (p.label_en or p.id)
            a = QAction(label or p.id, prof_menu)
            a.setCheckable(True)
            a.setChecked(p.id == active_pid)
            a.triggered.connect(lambda _checked=False, pid=p.id: self._orch.set_active_profile(pid))
            prof_group.addAction(a)
            prof_menu.addAction(a)

        # Idioma
        lang_menu = self._menu.addMenu(tr("tray.language"))
        lang_group = QActionGroup(lang_menu)
        lang_group.setExclusive(True)
        active_lang = self._orch.config.settings.active_language
        for lang in ("es", "en"):
            a = QAction(lang.upper(), lang_menu)
            a.setCheckable(True)
            a.setChecked(lang == active_lang)
            a.triggered.connect(lambda _checked=False, l=lang: self._orch.set_active_language(l))
            lang_group.addAction(a)
            lang_menu.addAction(a)

        self._menu.addSeparator()
        act_settings = QAction(tr("tray.settings"), self._menu)
        act_settings.triggered.connect(self._on_settings)
        self._menu.addAction(act_settings)
        self._menu.addSeparator()
        act_quit = QAction(tr("tray.quit"), self._menu)
        act_quit.triggered.connect(self._on_quit)
        self._menu.addAction(act_quit)
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        try:
            pid = self._orch.profiles.active_id
            label = self._orch.config.get_profile(pid).label_for(self._orch.config.settings.ui_language)
        except Exception:
            label = "—"
        lang = self._orch.config.settings.active_language.upper()
        state_label = tr(f"state.{self._current_state}")
        self.setToolTip(
            tr("tray.tooltip_template", profile=label, lang=lang, state=state_label)
        )

    def _on_state(self, state: str) -> None:
        self._current_state = state
        try:
            icon_state = "ready"
            if state in ("paused", "loading_model", "error"):
                icon_state = state
            elif state in ("recording", "transcribing", "executing"):
                icon_state = "recording"
            self.setIcon(_make_icon(icon_state))
        except Exception:
            logger.exception("tray_set_icon_failed")
        self._update_tooltip()
        self._rebuild_menu()

    def _on_activated(self, reason: int) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._on_show()

    def _toggle_pause(self) -> None:
        if self._orch.is_paused():
            self._orch.resume()
        else:
            self._orch.pause()
        self._rebuild_menu()

    def notify_minimized(self) -> None:
        self.showMessage(
            tr("tray.still_running.title"),
            tr("tray.still_running.body"),
            QSystemTrayIcon.Information,
            5000,
        )
