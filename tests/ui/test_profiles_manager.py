"""Tests del gestor de perfiles."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.mark.gui
def test_profiles_list_populated(qtbot, stub_orch):
    from origin.ui.engine_bridge import EngineBridge
    from origin.ui.i18n.tr import load as load_lang
    from origin.ui.pages.profiles_manager import ProfilesManagerPage

    orch, bus = stub_orch
    load_lang("es")
    bridge = EngineBridge(bus)
    page = ProfilesManagerPage(orch, bridge)
    qtbot.addWidget(page)
    assert page._list.count() == 2


@pytest.mark.gui
def test_delete_active_profile_falls_back(qtbot, stub_orch):
    from origin.ui.engine_bridge import EngineBridge
    from origin.ui.i18n.tr import load as load_lang
    from origin.ui.pages.profiles_manager import ProfilesManagerPage

    orch, bus = stub_orch
    load_lang("es")
    bridge = EngineBridge(bus)
    page = ProfilesManagerPage(orch, bridge)
    qtbot.addWidget(page)

    # Borrar 'flight' (active) — debería fallback a 'fps'.
    page._list.setCurrentRow(0)
    new_profiles = [p.model_dump() for p in orch.config.profiles if p.id != "flight"]
    settings = orch.config.settings.model_dump()
    settings["active_profile"] = "fps"
    page._apply_profiles_change(new_profiles, settings)
    assert orch.profiles.active_id == "fps"
