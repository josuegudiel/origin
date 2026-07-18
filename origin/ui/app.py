"""Bootstrap de la GUI: QApplication, single-instance, tema, tray + ventana.

Punto de entrada `run_app(config_path, dry_run, start_minimized) -> int`.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from ..engine.events import EventBus
from ..engine.paths import default_paths
from ..engine.runtime import Orchestrator
from . import theme
from .engine_bridge import EngineBridge
from .i18n.tr import load as load_lang
from .i18n.tr import retranslate_all
from .main_window import MainWindow
from .tray import OriginTray

logger = logging.getLogger(__name__)


def _single_instance_lock(lock_path: Path) -> QLockFile | None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lf = QLockFile(str(lock_path))
    lf.setStaleLockTime(0)
    if not lf.tryLock(100):
        return None
    return lf


def run_app(config_path: Path, dry_run: bool, start_minimized: bool) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # Permite que `closeEvent` no termine la app (la cierra el tray).
    app.setQuitOnLastWindowClosed(False)

    paths = default_paths()
    lock = _single_instance_lock(paths.lock_file)
    if lock is None:
        QMessageBox.warning(None, "Origin", "Otra instancia ya está corriendo.")
        return 1

    bus = EventBus()
    try:
        orch = Orchestrator(config_path, bus, dry_run=dry_run)
    except Exception as e:
        logger.exception("orchestrator_init_failed")
        QMessageBox.critical(None, "Origin", f"No se pudo iniciar el motor:\n{e}")
        return 2

    # Cargar idioma de la UI según settings.
    load_lang(orch.config.settings.ui_language)
    theme.apply_theme(app, orch.config.settings.theme)

    bridge = EngineBridge(bus)

    # Cuando cambia ui_language en runtime → recargar dict y retranslate.
    def _on_lang_change(_lang: str) -> None:
        load_lang(orch.config.settings.ui_language)
        retranslate_all()

    bridge.language_changed.connect(_on_lang_change)

    def _on_config_reloaded() -> None:
        load_lang(orch.config.settings.ui_language)
        retranslate_all()
        # Re-aplicar tema en caliente: sin esto el cambio de theme desde Settings
        # no surtía efecto hasta restart.
        theme.apply_theme(app, orch.config.settings.theme)

    bridge.config_reloaded.connect(_on_config_reloaded)

    # Ventana principal con close → tray.
    main_window = MainWindow(orch, bridge, on_close_to_tray=None)

    # Tray opcional.
    tray: OriginTray | None = None
    notify_state = {"first": True}
    if OriginTray.is_available():
        def show_dashboard() -> None:
            main_window.showNormal()
            main_window.raise_()
            main_window.activateWindow()

        def quit_origin() -> None:
            try:
                orch.shutdown()
            except Exception:
                logger.exception("shutdown_failed")
            tray.hide() if tray else None  # type: ignore[func-returns-value]
            app.quit()

        def go_settings() -> None:
            show_dashboard()
            main_window.navigate_to("settings")

        tray = OriginTray(orch, bridge, show_dashboard, quit_origin, on_open_settings=go_settings)
        tray.show()

        def close_to_tray() -> None:
            if notify_state["first"]:
                notify_state["first"] = False
                if tray is not None:
                    tray.notify_minimized()

        main_window._on_close_to_tray = close_to_tray  # noqa: SLF001
    else:
        # Sin tray: cerrar la ventana cierra la app.
        app.setQuitOnLastWindowClosed(True)

    orch.start()

    if start_minimized or orch.config.settings.start_minimized:
        main_window.hide()
    else:
        main_window.show()

    try:
        rc = app.exec()
    finally:
        try:
            orch.shutdown()
        except Exception:
            logger.exception("shutdown_on_exit_failed")
        lock.unlock()
    return int(rc)
