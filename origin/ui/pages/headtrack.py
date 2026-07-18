"""Página Head Tracking — control de cabeza por webcam (clon del núcleo de Beam).

Convierte la webcam en un head-tracker: pose 6DoF → OpenTrack (head-look en SC)
y/o gestos de cabeza → comandos. Vista en vivo de la pose, calibración,
sensibilidad por eje, salida OpenTrack y bindings de gestos.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...engine.config import GESTURES
from ...engine.headtrack import HeadTracker
from ...engine.runtime import Orchestrator
from ..engine_bridge import EngineBridge
from ..i18n.tr import register_retranslatable, tr

logger = logging.getLogger(__name__)

# (clave interna del eje en HeadTrackSettings, etiqueta corta)
_AXES = [
    ("yaw", "Yaw"), ("pitch", "Pitch"), ("roll", "Roll"),
    ("pos_x", "X"), ("pos_y", "Y"), ("pos_z", "Z"),
]
# Rango de las barras en vivo (grados para rotación, unidades para traslación).
_BAR_RANGE = {"yaw": 60, "pitch": 60, "roll": 60, "x": 30, "y": 30, "z": 30}


class HeadTrackPage(QWidget):
    def __init__(self, orch: Orchestrator, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._orch = orch
        self._bridge = bridge
        self._axis_widgets: dict[str, dict[str, Any]] = {}
        self._bars: dict[str, QProgressBar] = {}
        self._build_ui()
        self._populate()
        self._wire()
        register_retranslatable(self.retranslate)

    # ------------------------------------------------------------------ apply

    def _ht_dump(self) -> dict[str, Any]:
        return copy.deepcopy(self._orch.config.settings.headtrack.model_dump())

    def _set(self, path: list[str], value: Any) -> None:
        """Setea un campo (posiblemente anidado) del bloque headtrack y persiste
        el sub-bloque COMPLETO (evita que el merge shallow pierda otros campos)."""
        dump = self._ht_dump()
        node = dump
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
        try:
            self._orch.set_setting(headtrack=dump)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            logger.exception("headtrack_set_failed path=%s", path)
            QMessageBox.warning(self, tr("common.error"), str(e))

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)
        page = QWidget()
        scroll.setWidget(page)
        root = QVBoxLayout(page)

        # ----- General -----
        self._gb_general = QGroupBox()
        f = QFormLayout(self._gb_general)
        self._chk_enabled = QCheckBox()
        self._chk_enabled.toggled.connect(lambda v: self._set(["enabled"], bool(v)))
        self._lbl_enabled = QLabel()
        f.addRow(self._lbl_enabled, self._chk_enabled)

        cam_row = QHBoxLayout()
        self._cb_cam = QComboBox()
        self._cb_cam.currentIndexChanged.connect(
            lambda _i: self._set(["camera_index"], self._cb_cam.currentData() if self._cb_cam.currentData() is not None else 0)
        )
        self._btn_cam_refresh = QPushButton()
        self._btn_cam_refresh.clicked.connect(self._refresh_cameras)
        cam_row.addWidget(self._cb_cam, 1)
        cam_row.addWidget(self._btn_cam_refresh)
        self._lbl_cam = QLabel()
        f.addRow(self._lbl_cam, cam_row)

        self._sp_smoothing = QDoubleSpinBox()
        self._sp_smoothing.setRange(0.0, 0.95)
        self._sp_smoothing.setSingleStep(0.05)
        self._sp_smoothing.valueChanged.connect(lambda v: self._set(["smoothing"], float(v)))
        self._lbl_smoothing = QLabel()
        f.addRow(self._lbl_smoothing, self._sp_smoothing)

        self._sp_fps = QSpinBox()
        self._sp_fps.setRange(10, 120)
        self._sp_fps.valueChanged.connect(lambda v: self._set(["fps_target"], int(v)))
        self._lbl_fps = QLabel()
        f.addRow(self._lbl_fps, self._sp_fps)

        self._status_lbl = QLabel("—")
        self._lbl_status_cap = QLabel()
        f.addRow(self._lbl_status_cap, self._status_lbl)
        root.addWidget(self._gb_general)

        # ----- Pose en vivo -----
        self._gb_live = QGroupBox()
        lv = QFormLayout(self._gb_live)
        for key in ("yaw", "pitch", "roll", "x", "y", "z"):
            bar = QProgressBar()
            rng = _BAR_RANGE[key]
            bar.setRange(-rng, rng)
            bar.setValue(0)
            bar.setFormat(f"{key} %v")
            self._bars[key] = bar
            lv.addRow(key, bar)
        self._btn_center = QPushButton()
        self._btn_center.clicked.connect(self._orch.calibrate_head)
        lv.addRow("", self._btn_center)
        self._gesture_lbl = QLabel("—")
        self._lbl_last_gesture = QLabel()
        lv.addRow(self._lbl_last_gesture, self._gesture_lbl)
        root.addWidget(self._gb_live)

        # ----- Ejes (sensibilidad / invert / deadzone) -----
        self._gb_axes = QGroupBox()
        av = QVBoxLayout(self._gb_axes)
        for key, label in _AXES:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            sens = QDoubleSpinBox(); sens.setRange(0.0, 8.0); sens.setSingleStep(0.1)
            sens.valueChanged.connect(lambda v, k=key: self._set([k, "sensitivity"], float(v)))
            inv = QCheckBox("invert")
            inv.toggled.connect(lambda v, k=key: self._set([k, "invert"], bool(v)))
            dz = QDoubleSpinBox(); dz.setRange(0.0, 45.0); dz.setSingleStep(1.0)
            dz.valueChanged.connect(lambda v, k=key: self._set([k, "deadzone"], float(v)))
            row.addWidget(QLabel("sens")); row.addWidget(sens)
            row.addWidget(inv)
            row.addWidget(QLabel("deadzone")); row.addWidget(dz)
            row.addStretch(1)
            av.addLayout(row)
            self._axis_widgets[key] = {"sens": sens, "inv": inv, "dz": dz}
        root.addWidget(self._gb_axes)

        # ----- OpenTrack -----
        self._gb_ot = QGroupBox()
        f = QFormLayout(self._gb_ot)
        self._chk_ot = QCheckBox()
        self._chk_ot.toggled.connect(lambda v: self._set(["opentrack", "enabled"], bool(v)))
        self._lbl_ot_enabled = QLabel()
        f.addRow(self._lbl_ot_enabled, self._chk_ot)
        self._ed_ot_host = QLineEdit()
        self._ed_ot_host.editingFinished.connect(
            lambda: self._set(["opentrack", "host"], self._ed_ot_host.text())
        )
        self._lbl_ot_host = QLabel()
        f.addRow(self._lbl_ot_host, self._ed_ot_host)
        self._sp_ot_port = QSpinBox(); self._sp_ot_port.setRange(1, 65535)
        self._sp_ot_port.valueChanged.connect(lambda v: self._set(["opentrack", "port"], int(v)))
        self._lbl_ot_port = QLabel()
        f.addRow(self._lbl_ot_port, self._sp_ot_port)
        self._lbl_ot_hint = QLabel()
        self._lbl_ot_hint.setWordWrap(True)
        f.addRow("", self._lbl_ot_hint)
        root.addWidget(self._gb_ot)

        # ----- Gestos → comandos -----
        self._gb_gestures = QGroupBox()
        gv = QVBoxLayout(self._gb_gestures)
        self._tbl_gestures = QTableWidget(0, 3)
        self._tbl_gestures.horizontalHeader().setStretchLastSection(True)
        self._tbl_gestures.verticalHeader().setVisible(False)
        gv.addWidget(self._tbl_gestures)
        gbtn = QHBoxLayout()
        self._btn_g_add = QPushButton()
        self._btn_g_add.clicked.connect(self._add_gesture_row)
        self._btn_g_del = QPushButton()
        self._btn_g_del.clicked.connect(self._del_gesture_row)
        gbtn.addWidget(self._btn_g_add); gbtn.addWidget(self._btn_g_del); gbtn.addStretch(1)
        gv.addLayout(gbtn)
        root.addWidget(self._gb_gestures)

        root.addStretch(1)
        self.retranslate()

    # ------------------------------------------------------------------ populate

    def _populate(self) -> None:
        s = self._orch.config.settings.headtrack
        for w in (self._chk_enabled, self._sp_smoothing, self._sp_fps, self._chk_ot,
                  self._ed_ot_host, self._sp_ot_port):
            w.blockSignals(True)
        try:
            self._chk_enabled.setChecked(s.enabled)
            self._sp_smoothing.setValue(s.smoothing)
            self._sp_fps.setValue(s.fps_target)
            self._chk_ot.setChecked(s.opentrack.enabled)
            self._ed_ot_host.setText(s.opentrack.host)
            self._sp_ot_port.setValue(s.opentrack.port)
        finally:
            for w in (self._chk_enabled, self._sp_smoothing, self._sp_fps, self._chk_ot,
                      self._ed_ot_host, self._sp_ot_port):
                w.blockSignals(False)
        for key, _ in _AXES:
            axis = getattr(s, key)
            ws = self._axis_widgets[key]
            for w in ws.values():
                w.blockSignals(True)
            ws["sens"].setValue(axis.sensitivity)
            ws["inv"].setChecked(axis.invert)
            ws["dz"].setValue(axis.deadzone)
            for w in ws.values():
                w.blockSignals(False)
        self._refresh_cameras()
        self._reload_gestures()

    def _refresh_cameras(self) -> None:
        cur = self._orch.config.settings.headtrack.camera_index
        self._cb_cam.blockSignals(True)
        self._cb_cam.clear()
        cams = HeadTracker.list_cameras()
        if not cams:
            # Sin cv2/cámaras: igual dejamos elegir el índice configurado.
            self._cb_cam.addItem(tr("headtrack.no_cameras"), cur)
        else:
            for i in cams:
                self._cb_cam.addItem(f"{tr('headtrack.camera')} {i}", i)
            idx = self._cb_cam.findData(cur)
            if idx >= 0:
                self._cb_cam.setCurrentIndex(idx)
        self._cb_cam.blockSignals(False)

    def _reload_gestures(self) -> None:
        bindings = self._orch.config.settings.headtrack.gestures
        self._tbl_gestures.blockSignals(True)
        self._tbl_gestures.setRowCount(len(bindings))
        for r, b in enumerate(bindings):
            self._set_gesture_row(r, b.gesture, b.command_id, b.enabled)
        self._tbl_gestures.blockSignals(False)

    def _set_gesture_row(self, r: int, gesture: str, command_id: str, enabled: bool) -> None:
        combo = QComboBox()
        combo.addItems(list(GESTURES))
        combo.setCurrentText(gesture)
        combo.currentTextChanged.connect(lambda _t: self._save_gestures())
        self._tbl_gestures.setCellWidget(r, 0, combo)
        item = QTableWidgetItem(command_id)
        self._tbl_gestures.setItem(r, 1, item)
        chk = QCheckBox()
        chk.setChecked(enabled)
        chk.toggled.connect(lambda _v: self._save_gestures())
        self._tbl_gestures.setCellWidget(r, 2, chk)

    def _add_gesture_row(self) -> None:
        r = self._tbl_gestures.rowCount()
        self._tbl_gestures.insertRow(r)
        self._set_gesture_row(r, GESTURES[0], "", True)

    def _del_gesture_row(self) -> None:
        r = self._tbl_gestures.currentRow()
        if r >= 0:
            self._tbl_gestures.removeRow(r)
            self._save_gestures()

    def _save_gestures(self) -> None:
        bindings = []
        for r in range(self._tbl_gestures.rowCount()):
            combo = self._tbl_gestures.cellWidget(r, 0)
            cmd_item = self._tbl_gestures.item(r, 1)
            chk = self._tbl_gestures.cellWidget(r, 2)
            cmd_id = (cmd_item.text().strip() if cmd_item else "")
            if not cmd_id:
                continue  # fila incompleta, se ignora hasta que tenga command_id
            bindings.append({
                "gesture": combo.currentText(),
                "command_id": cmd_id,
                "enabled": chk.isChecked(),
            })
        self._set(["gestures"], bindings)

    # ------------------------------------------------------------------ wiring

    def _wire(self) -> None:
        self._bridge.head_pose.connect(self._on_pose)
        self._bridge.head_track_state.connect(self._on_state)
        self._bridge.head_gesture.connect(self._on_gesture)
        # Guardar gestos cuando el usuario edita la celda de command_id.
        self._tbl_gestures.itemChanged.connect(lambda _i: self._save_gestures())

    def _on_pose(self, p: dict[str, Any]) -> None:
        for key in ("yaw", "pitch", "roll", "x", "y", "z"):
            bar = self._bars.get(key)
            if bar is not None:
                rng = _BAR_RANGE[key]
                bar.setValue(int(max(-rng, min(rng, p.get(key, 0.0)))))

    def _on_state(self, p: dict[str, Any]) -> None:
        state = p.get("state", "")
        err = p.get("error")
        self._status_lbl.setText(tr(f"headtrack.state.{state}") if state else "—")
        if err:
            self._status_lbl.setText(f"{tr('headtrack.state.error')}: {err}")

    def _on_gesture(self, p: dict[str, Any]) -> None:
        self._gesture_lbl.setText(p.get("gesture", "—"))

    # ------------------------------------------------------------------ i18n

    def retranslate(self) -> None:
        self._gb_general.setTitle(tr("headtrack.general"))
        self._lbl_enabled.setText(tr("headtrack.enabled"))
        self._lbl_cam.setText(tr("headtrack.camera"))
        self._btn_cam_refresh.setText(tr("settings.mic_refresh"))
        self._lbl_smoothing.setText(tr("headtrack.smoothing"))
        self._lbl_fps.setText(tr("headtrack.fps"))
        self._lbl_status_cap.setText(tr("headtrack.status"))
        self._gb_live.setTitle(tr("headtrack.live"))
        self._btn_center.setText(tr("headtrack.center"))
        self._lbl_last_gesture.setText(tr("headtrack.last_gesture"))
        self._gb_axes.setTitle(tr("headtrack.axes"))
        self._gb_ot.setTitle(tr("headtrack.opentrack"))
        self._lbl_ot_enabled.setText(tr("headtrack.opentrack_enabled"))
        self._lbl_ot_host.setText(tr("headtrack.host"))
        self._lbl_ot_port.setText(tr("headtrack.port"))
        self._lbl_ot_hint.setText(tr("headtrack.opentrack_hint"))
        self._gb_gestures.setTitle(tr("headtrack.gestures"))
        self._btn_g_add.setText(tr("commands.add"))
        self._btn_g_del.setText(tr("commands.delete"))
        self._tbl_gestures.setHorizontalHeaderLabels([
            tr("headtrack.gesture"), tr("headtrack.command_id"), tr("headtrack.gesture_on"),
        ])
