"""Smoke del tray: el menú se construye con perfiles y permite click."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.mark.gui
def test_tray_menu_contains_profiles(qtbot, stub_orch):
    from PySide6.QtWidgets import QSystemTrayIcon

    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("System tray no disponible en este entorno")

    from origin.ui.engine_bridge import EngineBridge
    from origin.ui.i18n.tr import load as load_lang
    from origin.ui.tray import OriginTray

    orch, bus = stub_orch
    load_lang("es")
    bridge = EngineBridge(bus)
    tray = OriginTray(orch, bridge, on_show_dashboard=lambda: None, on_quit=lambda: None)
    actions = tray._menu.actions()
    texts = [a.text() for a in actions]
    assert any("perfil" in t.lower() or "profile" in t.lower() for t in texts)
    tray.hide()
