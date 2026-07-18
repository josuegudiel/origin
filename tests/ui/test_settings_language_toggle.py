"""Cambiar el idioma de la UI debe repintar labels."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.mark.gui
def test_ui_language_change_relabels_sidebar(qtbot, stub_orch):
    from origin.ui.engine_bridge import EngineBridge
    from origin.ui.i18n.tr import load as load_lang
    from origin.ui.i18n.tr import retranslate_all
    from origin.ui.main_window import MainWindow

    orch, bus = stub_orch
    load_lang("es")
    bridge = EngineBridge(bus)
    w = MainWindow(orch, bridge)
    qtbot.addWidget(w)
    es_label = w._sidebar.item(0).text()
    load_lang("en")
    retranslate_all()
    en_label = w._sidebar.item(0).text()
    assert es_label != en_label
