"""Smoke test del ScriptEditorDialog."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.mark.gui
def test_script_editor_with_empty_steps(qtbot):
    from origin.ui.widgets.script_editor import ScriptEditorDialog

    dlg = ScriptEditorDialog(steps=[])
    qtbot.addWidget(dlg)
    assert dlg._list.count() == 0


@pytest.mark.gui
def test_script_editor_with_initial_steps(qtbot):
    from origin.engine.config import KeyStep, SayStep, WaitStep
    from origin.ui.widgets.script_editor import ScriptEditorDialog

    steps = [
        KeyStep(combo="alt+n"),
        WaitStep(ms=200),
        SayStep(text_es="ack"),
    ]
    dlg = ScriptEditorDialog(steps=steps)
    qtbot.addWidget(dlg)
    assert dlg._list.count() == 3
    assert dlg.result_steps == steps


@pytest.mark.gui
def test_script_editor_delete_step(qtbot):
    from origin.engine.config import KeyStep
    from origin.ui.widgets.script_editor import ScriptEditorDialog

    steps = [KeyStep(combo="a"), KeyStep(combo="b")]
    dlg = ScriptEditorDialog(steps=steps)
    qtbot.addWidget(dlg)
    dlg._list.setCurrentRow(0)
    dlg._on_delete()
    assert len(dlg.result_steps) == 1
    assert dlg.result_steps[0].combo == "b"
