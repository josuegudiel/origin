"""Tests del editor de comandos."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.mark.gui
def test_editor_renders_commands_of_active_profile(qtbot, stub_orch):
    from origin.ui.engine_bridge import EngineBridge
    from origin.ui.i18n.tr import load as load_lang
    from origin.ui.pages.commands_editor import CommandsEditorPage

    orch, bus = stub_orch
    load_lang("es")
    bridge = EngineBridge(bus)
    page = CommandsEditorPage(orch, bridge)
    qtbot.addWidget(page)
    assert page._table.rowCount() == 1  # 'request_landing' en perfil 'flight'
    assert page._table.item(0, 0).text() == "request_landing"


@pytest.mark.gui
def test_editor_validates_invalid_keys_cell(qtbot, stub_orch):
    from origin.ui.engine_bridge import EngineBridge
    from origin.ui.i18n.tr import load as load_lang
    from origin.ui.pages.commands_editor import CommandsEditorPage

    orch, bus = stub_orch
    load_lang("es")
    bridge = EngineBridge(bus)
    page = CommandsEditorPage(orch, bridge)
    qtbot.addWidget(page)

    # Cambiar la celda de keys (col=3) a algo inválido.
    page._table.item(0, 3).setText("notakey+++")
    assert page._table.item(0, 3).toolTip() != ""
