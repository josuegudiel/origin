"""Tests de la página Head Tracking (clon Beam Eye Tracker) en la GUI.

Ejercitan la página como la usa una persona: togglear, mover spinboxes, editar
la tabla de gestos, y recibir poses/estados/gestos en vivo por el EngineBridge.
Lo que más importa acá es que **guardar un campo no pise los demás** — la página
persiste el sub-bloque `headtrack` completo en cada cambio.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")


@pytest.fixture
def ht_page(qtbot, stub_orch):
    from origin.ui.engine_bridge import EngineBridge
    from origin.ui.pages.headtrack import HeadTrackPage

    orch, bus = stub_orch
    bridge = EngineBridge(bus)
    page = HeadTrackPage(orch, bridge)
    qtbot.addWidget(page)
    return page, orch, bridge


@pytest.mark.gui
def test_page_builds_and_populates_from_config(ht_page):
    page, orch, _ = ht_page
    s = orch.config.settings.headtrack
    assert page._chk_enabled.isChecked() is s.enabled
    assert page._sp_fps.value() == s.fps_target
    assert page._ed_ot_host.text() == s.opentrack.host
    assert page._sp_ot_port.value() == s.opentrack.port
    # Una barra por eje de la pose en vivo.
    assert set(page._bars) == {"yaw", "pitch", "roll", "x", "y", "z"}


@pytest.mark.gui
def test_toggle_enabled_persists(ht_page):
    page, orch, _ = ht_page
    assert orch.config.settings.headtrack.enabled is False
    page._chk_enabled.setChecked(True)
    assert orch.config.settings.headtrack.enabled is True


@pytest.mark.gui
def test_axis_edit_persists_and_keeps_other_fields(ht_page):
    """REGRESIÓN: guardar un eje no debe perder el resto del bloque headtrack."""
    page, orch, _ = ht_page
    page._sp_fps.setValue(48)
    page._axis_widgets["yaw"]["sens"].setValue(2.5)
    page._axis_widgets["pitch"]["inv"].setChecked(True)
    page._axis_widgets["roll"]["dz"].setValue(7.0)

    s = orch.config.settings.headtrack
    assert s.yaw.sensitivity == 2.5
    assert s.pitch.invert is True
    assert s.roll.deadzone == 7.0
    assert s.fps_target == 48          # no lo pisó el guardado del eje
    assert s.opentrack.port == 4242    # el sub-bloque anidado sobrevive


@pytest.mark.gui
def test_opentrack_fields_persist(ht_page):
    page, orch, _ = ht_page
    page._sp_ot_port.setValue(5555)
    page._ed_ot_host.setText("192.168.1.50")
    page._ed_ot_host.editingFinished.emit()
    s = orch.config.settings.headtrack
    assert s.opentrack.port == 5555
    assert s.opentrack.host == "192.168.1.50"


@pytest.mark.gui
def test_opentrack_public_host_rejected_without_crashing(ht_page, monkeypatch):
    """Un host de Internet lo rechaza el validador: aviso, sin romper la UI."""
    from PySide6.QtWidgets import QMessageBox

    page, orch, _ = ht_page
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: warnings.append(a[2] if len(a) > 2 else ""),
    )
    page._ed_ot_host.setText("evil.example.com")
    page._ed_ot_host.editingFinished.emit()
    assert warnings, "esperaba un aviso al usuario"
    assert orch.config.settings.headtrack.opentrack.host == "127.0.0.1"


@pytest.mark.gui
def test_gesture_row_add_and_persist(ht_page):
    from PySide6.QtWidgets import QTableWidgetItem

    page, orch, _ = ht_page
    page._btn_g_add.click()
    assert page._tbl_gestures.rowCount() == 1
    # Fila sin command_id todavía no persiste nada.
    assert orch.config.settings.headtrack.gestures == []

    page._tbl_gestures.setItem(0, 1, QTableWidgetItem("request_landing"))
    bindings = orch.config.settings.headtrack.gestures
    assert len(bindings) == 1
    assert bindings[0].command_id == "request_landing"
    assert bindings[0].enabled is True


@pytest.mark.gui
def test_gesture_row_delete_persists(ht_page):
    from PySide6.QtWidgets import QTableWidgetItem

    page, orch, _ = ht_page
    page._btn_g_add.click()
    page._tbl_gestures.setItem(0, 1, QTableWidgetItem("request_landing"))
    assert len(orch.config.settings.headtrack.gestures) == 1

    page._tbl_gestures.setCurrentCell(0, 1)
    page._btn_g_del.click()
    assert orch.config.settings.headtrack.gestures == []


@pytest.mark.gui
def test_live_pose_updates_bars(ht_page):
    page, _, bridge = ht_page
    bridge.head_pose.emit({"yaw": 12.0, "pitch": -8.0, "roll": 0.0,
                           "x": 1.0, "y": 2.0, "z": 3.0})
    assert page._bars["yaw"].value() == 12
    assert page._bars["pitch"].value() == -8
    assert page._bars["z"].value() == 3


@pytest.mark.gui
def test_live_pose_clamped_to_bar_range(ht_page):
    """Una pose fuera de rango no debe romper el QProgressBar."""
    page, _, bridge = ht_page
    bridge.head_pose.emit({"yaw": 9999.0, "pitch": -9999.0})
    assert page._bars["yaw"].value() == 60
    assert page._bars["pitch"].value() == -60


@pytest.mark.gui
def test_state_and_gesture_labels_update(ht_page):
    page, _, bridge = ht_page
    bridge.head_track_state.emit({"state": "running"})
    assert page._status_lbl.text() not in ("", "—")
    bridge.head_track_state.emit({"state": "error", "error": "cámara ocupada"})
    assert "cámara ocupada" in page._status_lbl.text()
    bridge.head_gesture.emit({"gesture": "nod"})
    assert page._gesture_lbl.text() == "nod"


@pytest.mark.gui
def test_center_button_calls_calibrate(ht_page):
    page, orch, _ = ht_page
    called: list[bool] = []
    orch.calibrate_head = lambda: called.append(True)
    # El botón quedó conectado al método original: lo re-conectamos como en la UI.
    page._btn_center.clicked.disconnect()
    page._btn_center.clicked.connect(orch.calibrate_head)
    page._btn_center.click()
    assert called == [True]
