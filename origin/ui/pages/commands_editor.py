"""Editor de comandos del perfil activo.

QTableWidget con auto-save: cada cambio valida y, si OK, persiste el commands.yaml
completo (todos los perfiles intactos excepto el editado).

Phrases y keys son comma-separated dentro de la celda — el placeholder y el
tooltip lo dejan claro. Validación inline: celda con borde rojo + tooltip con
el mensaje de error. Si una fila tiene errores, el save de esa fila se omite
pero los cambios en otras filas válidas se guardan.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...engine import config as cfgmod
from ...engine import keypress
from ...engine.runtime import Orchestrator
from ..engine_bridge import EngineBridge
from ..i18n.tr import register_retranslatable, tr

logger = logging.getLogger(__name__)

COLS = [
    ("id",              "commands.col.id"),
    ("phrases_es",      "commands.col.phrases_es"),
    ("phrases_en",      "commands.col.phrases_en"),
    ("keys",            "commands.col.keys"),
    ("label_es",        "commands.col.label_es"),
    ("label_en",        "commands.col.label_en"),
    ("description_es",  "commands.col.description_es"),
    ("description_en",  "commands.col.description_en"),
]


def _split_list(text: str) -> list[str]:
    return [s.strip() for s in text.split(",") if s.strip()]


def _join_list(items: list[str]) -> str:
    return ", ".join(items)


class CommandsEditorPage(QWidget):
    def __init__(
        self,
        orch: Orchestrator,
        bridge: EngineBridge,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._orch = orch
        self._bridge = bridge
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_now)
        self._suppress_save = False
        self._build_ui()
        self._wire()
        self._reload_from_orch()
        register_retranslatable(self.retranslate)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self._lbl_profile = QLabel()
        self._profile_combo = QComboBox()
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)
        bar.addWidget(self._lbl_profile)
        bar.addWidget(self._profile_combo, 1)

        self._btn_add = QPushButton()
        self._btn_dup = QPushButton()
        self._btn_del = QPushButton()
        self._btn_test = QPushButton()
        self._btn_script = QPushButton()
        for btn, slot in (
            (self._btn_add, self._on_add),
            (self._btn_dup, self._on_duplicate),
            (self._btn_del, self._on_delete),
            (self._btn_test, self._on_test),
            (self._btn_script, self._on_edit_script),
        ):
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        root.addLayout(bar)

        self._table = QTableWidget(0, len(COLS), self)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self._table, 1)

        self.retranslate()

    def _wire(self) -> None:
        self._bridge.config_reloaded.connect(self._reload_from_orch)
        self._bridge.profile_changed.connect(self._on_external_profile_changed)

    # ------------------------------------------------------------------ Carga

    def _reload_from_orch(self) -> None:
        self._suppress_save = True
        try:
            cf = self._orch.config
            self._profile_combo.blockSignals(True)
            self._profile_combo.clear()
            self._profile_combo.addItems([p.id for p in cf.profiles])
            self._profile_combo.setCurrentText(self._orch.profiles.active_id)
            self._profile_combo.blockSignals(False)
            self._render_table()
        finally:
            self._suppress_save = False

    def _render_table(self) -> None:
        self._suppress_save = True
        try:
            cf = self._orch.config
            pid = self._profile_combo.currentText() or self._orch.profiles.active_id
            try:
                profile = cf.get_profile(pid)
            except KeyError:
                self._table.setRowCount(0)
                self._last_rendered_profile = None
                return
            # Track el perfil renderizado para que un cambio de combo pueda
            # flushear el save pendiente al perfil correcto, no al nuevo.
            self._last_rendered_profile = pid
            self._table.setRowCount(len(profile.commands))
            for r, cmd in enumerate(profile.commands):
                self._set_cell(r, 0, cmd.id)
                self._set_cell(r, 1, _join_list(cmd.phrases_es))
                self._set_cell(r, 2, _join_list(cmd.phrases_en))
                self._set_cell(r, 3, _join_list(cmd.keys))
                self._set_cell(r, 4, cmd.label_es or "")
                self._set_cell(r, 5, cmd.label_en or "")
                self._set_cell(r, 6, cmd.description_es or "")
                self._set_cell(r, 7, cmd.description_en or "")
        finally:
            self._suppress_save = False

    def _set_cell(self, row: int, col: int, value: str) -> None:
        item = QTableWidgetItem(value)
        self._table.setItem(row, col, item)

    # ------------------------------------------------------------------ Edit ops

    def _on_add(self) -> None:
        new_id, ok = QInputDialog.getText(self, tr("commands.add"), "ID:")
        if not ok or not new_id.strip():
            return
        new_id = new_id.strip()
        if not cfgmod.ID_RE.match(new_id):
            QMessageBox.warning(self, tr("common.error"), tr("commands.error.invalid_keys", err="id"))
            return
        cf = self._orch.config
        pid = self._profile_combo.currentText()
        prof = cf.get_profile(pid)
        if any(c.id == new_id for c in prof.commands):
            QMessageBox.warning(self, tr("common.error"), tr("commands.error.duplicate_id"))
            return
        new_cmd_dict = {
            "id": new_id,
            "phrases_es": [new_id.replace("_", " ")],
            "phrases_en": [],
            "keys": ["a"],
            "label_es": new_id.replace("_", " ").title(),
            "label_en": new_id.replace("_", " ").title(),
        }
        self._apply_profile_change(pid, [*[c.model_dump() for c in prof.commands], new_cmd_dict])
        self._render_table()

    def _on_duplicate(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        cf = self._orch.config
        pid = self._profile_combo.currentText()
        prof = cf.get_profile(pid)
        src = prof.commands[row]
        new_id = f"{src.id}_copy"
        n = 1
        while any(c.id == new_id for c in prof.commands):
            n += 1
            new_id = f"{src.id}_copy{n}"
        dup = src.model_dump()
        dup["id"] = new_id
        new_cmds = [c.model_dump() for c in prof.commands]
        new_cmds.insert(row + 1, dup)
        self._apply_profile_change(pid, new_cmds)
        self._render_table()

    def _on_delete(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        cf = self._orch.config
        pid = self._profile_combo.currentText()
        prof = cf.get_profile(pid)
        new_cmds = [c.model_dump() for i, c in enumerate(prof.commands) if i != row]
        self._apply_profile_change(pid, new_cmds)
        self._render_table()

    def _on_test(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        cf = self._orch.config
        pid = self._profile_combo.currentText()
        prof = cf.get_profile(pid)
        cmd = prof.commands[row]
        confirm = QMessageBox.question(
            self,
            tr("commands.test"),
            tr("commands.test_countdown", n=3) + "\n" + ", ".join(cmd.keys),
        )
        if confirm != QMessageBox.Yes:
            return
        # Countdown 3s para alt-tab al juego.
        QTimer.singleShot(3000, lambda: self._orch.execute_command_test(cmd.id, profile_id=pid))

    def _on_edit_script(self) -> None:
        from ..widgets.script_editor import ScriptEditorDialog

        row = self._table.currentRow()
        if row < 0:
            return
        cf = self._orch.config
        pid = self._profile_combo.currentText()
        prof = cf.get_profile(pid)
        cmd = prof.commands[row]
        current_steps = list(cmd.steps) if cmd.steps else []
        dlg = ScriptEditorDialog(steps=current_steps, parent=self)
        if dlg.exec() != ScriptEditorDialog.Accepted:
            return
        new_steps = dlg.result_steps
        # Build el comando con steps actualizados; mantenemos keys como sugar legacy.
        new_cmd_dump = cmd.model_dump()
        new_cmd_dump["steps"] = [s.model_dump() for s in new_steps] if new_steps else None
        new_commands = []
        for c in prof.commands:
            if c.id == cmd.id:
                new_commands.append(new_cmd_dump)
            else:
                new_commands.append(c.model_dump())
        self._apply_profile_change(pid, new_commands)

    def _on_profile_changed(self, _pid: str) -> None:
        if self._suppress_save:
            return
        # Si hay un save pendiente del perfil anterior, flushearlo antes del re-render
        # — sin esto, los edits del perfil viejo se perdían cuando el usuario
        # cambiaba el combo durante el debounce de 500 ms.
        if self._save_timer.isActive():
            self._save_timer.stop()
            try:
                pid_prev = getattr(self, "_last_rendered_profile", None)
                if pid_prev:
                    # Pasamos profile_id explícito — el combo ya cambió al perfil
                    # nuevo y leer currentText() haría el lookup de steps/say_*
                    # contra el perfil equivocado.
                    cmds = self._collect_table_as_commands(profile_id=pid_prev)
                    self._apply_profile_change(pid_prev, cmds)
            except Exception:
                logger.exception("flush_pending_save_on_profile_change_failed")
        self._render_table()

    def _on_external_profile_changed(self, pid: str) -> None:
        if self._profile_combo.currentText() != pid:
            self._profile_combo.setCurrentText(pid)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress_save:
            return
        self._validate_cell(item)
        self._save_timer.start()

    # ------------------------------------------------------------------ Validación + save

    def _validate_cell(self, item: QTableWidgetItem) -> None:
        col = item.column()
        text = item.text() or ""
        err: str | None = None
        if col == 0:  # id
            if not cfgmod.ID_RE.match(text):
                err = "id inválido"
        elif col == 3:  # keys
            errs = keypress.validate_all(_split_list(text))
            if errs:
                err = "; ".join(errs)
        if err:
            item.setBackground(QBrush(QColor(255, 220, 220)))
            item.setToolTip(err)
        else:
            item.setData(Qt.BackgroundRole, None)
            item.setToolTip("")

    def _collect_table_as_commands(self, profile_id: str | None = None) -> list[dict[str, Any]]:
        """Reconstruye los comandos desde la tabla.

        `profile_id` permite forzar el perfil contra el cual hacer el lookup de
        campos preservados (`steps`, `say_*`). Sin esto, el flush en
        `_on_profile_changed` lookupea contra el perfil NUEVO (combo ya cambió)
        en vez del que renderizó la tabla.

        Mergeo cuidadoso: la tabla solo edita columnas planas (id, phrases, keys,
        labels, descriptions). Los campos `steps`, `say_es`, `say_en`, `say_key`
        del comando original se preservan vía lookup por id.
        """
        cf = self._orch.config
        pid = profile_id or (
            self._profile_combo.currentText() or self._orch.profiles.active_id
        )
        try:
            original_by_id = {c.id: c for c in cf.get_profile(pid).commands}
        except KeyError:
            original_by_id = {}

        out: list[dict[str, Any]] = []
        for r in range(self._table.rowCount()):
            row = {
                col[0]: (self._table.item(r, i).text() if self._table.item(r, i) else "")
                for i, col in enumerate(COLS)
            }
            new_id = row["id"].strip()
            original = original_by_id.get(new_id)
            cmd = {
                "id": new_id,
                "phrases_es": _split_list(row["phrases_es"]),
                "phrases_en": _split_list(row["phrases_en"]),
                "keys": _split_list(row["keys"]),
                "label_es": row["label_es"].strip() or None,
                "label_en": row["label_en"].strip() or None,
                "description_es": row["description_es"].strip() or None,
                "description_en": row["description_en"].strip() or None,
                # ===== preserved (no editables desde la tabla) =====
                "steps": [s.model_dump(by_alias=True) for s in original.steps] if (original and original.steps) else None,
                "say_es": original.say_es if original else None,
                "say_en": original.say_en if original else None,
                "say_key": original.say_key if original else None,
            }
            out.append(cmd)
        return out

    def _save_now(self) -> None:
        pid = self._profile_combo.currentText() or self._orch.profiles.active_id
        cmds = self._collect_table_as_commands()
        self._apply_profile_change(pid, cmds)

    def _apply_profile_change(self, profile_id: str, new_commands: list[dict[str, Any]]) -> None:
        cf = self._orch.config
        prof = cf.get_profile(profile_id)
        new_profile = {
            "id": prof.id,
            "label_es": prof.label_es,
            "label_en": prof.label_en,
            "description_es": prof.description_es,
            "description_en": prof.description_en,
            "commands": new_commands,
        }
        new_profiles = [
            new_profile if p.id == profile_id else p.model_dump(by_alias=True)
            for p in cf.profiles
        ]
        new_dump = {
            "version": 3,
            "settings": cf.settings.model_dump(),
            "profiles": new_profiles,
        }
        try:
            new_cf = cfgmod.CommandsFileV2.model_validate(new_dump)
        except Exception as e:
            logger.warning("commands_edit_invalid err=%s", e)
            return
        try:
            cfgmod.save_atomic(new_cf, self._orch.config_path)
        except Exception:
            logger.exception("commands_save_failed")
            return
        # El watchdog disparará reload_config; recargamos directo por si está deshabilitado.
        self._orch.reload_config()

    # ------------------------------------------------------------------ i18n

    def retranslate(self) -> None:
        self._lbl_profile.setText(tr("commands.profile_label"))
        self._btn_add.setText(tr("commands.add"))
        self._btn_dup.setText(tr("commands.duplicate"))
        self._btn_del.setText(tr("commands.delete"))
        self._btn_test.setText(tr("commands.test"))
        self._btn_script.setText(tr("script.edit"))
        headers = [tr(label_key) for _, label_key in COLS]
        self._table.setHorizontalHeaderLabels(headers)
