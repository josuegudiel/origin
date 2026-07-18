"""Gestor de perfiles: crear, duplicar, borrar, importar, exportar, renombrar labels."""
from __future__ import annotations

import logging
from typing import Any

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...engine import config as cfgmod
from ...engine.runtime import Orchestrator
from ..engine_bridge import EngineBridge
from ..i18n.tr import register_retranslatable, tr

logger = logging.getLogger(__name__)


def _collect_combos_from_raw_profile(raw: dict[str, Any]) -> set[str]:
    """Extrae las combinaciones de teclas de un perfil crudo (dict del YAML),
    incluyendo tanto `keys:` como los `KeyStep` de `steps:` (recursivo en
    if/repeat). Usado para la preview de seguridad al importar."""
    combos: set[str] = set()

    def walk_steps(steps: Any) -> None:
        if not isinstance(steps, list):
            return
        for s in steps:
            if not isinstance(s, dict):
                continue
            t = s.get("type")
            if t == "key" and isinstance(s.get("combo"), str):
                combos.add(s["combo"])
            elif t == "if":
                walk_steps(s.get("then"))
                walk_steps(s.get("else"))
            elif t == "repeat":
                walk_steps(s.get("steps"))

    for cmd in raw.get("commands", []):
        if not isinstance(cmd, dict):
            continue
        for k in cmd.get("keys", []) or []:
            if isinstance(k, str):
                combos.add(k)
        walk_steps(cmd.get("steps"))
    return combos


class ProfilesManagerPage(QWidget):
    def __init__(self, orch: Orchestrator, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._orch = orch
        self._bridge = bridge
        self._editing_id: str | None = None
        self._suppress = False
        self._build_ui()
        self._wire()
        self._reload()
        register_retranslatable(self.retranslate)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        left = QWidget()
        lv = QVBoxLayout(left)
        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._on_select)
        lv.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._btn_new = QPushButton()
        self._btn_dup = QPushButton()
        self._btn_del = QPushButton()
        self._btn_imp = QPushButton()
        self._btn_exp = QPushButton()
        for b, slot in (
            (self._btn_new, self._on_new),
            (self._btn_dup, self._on_dup),
            (self._btn_del, self._on_delete),
            (self._btn_imp, self._on_import),
            (self._btn_exp, self._on_export),
        ):
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        lv.addLayout(btn_row)

        right = QGroupBox()
        self._right_box = right
        form = QFormLayout(right)
        self._lbl_id = QLabel()
        self._inp_label_es = QLineEdit()
        self._inp_label_en = QLineEdit()
        self._inp_desc_es = QTextEdit()
        self._inp_desc_es.setMaximumHeight(60)
        self._inp_desc_en = QTextEdit()
        self._inp_desc_en.setMaximumHeight(60)
        self._cnt_label = QLabel()
        form.addRow("ID:", self._lbl_id)
        self._lbl_label_es_row = QLabel("label_es:")
        self._lbl_label_en_row = QLabel("label_en:")
        self._lbl_desc_es_row = QLabel("description_es:")
        self._lbl_desc_en_row = QLabel("description_en:")
        form.addRow(self._lbl_label_es_row, self._inp_label_es)
        form.addRow(self._lbl_label_en_row, self._inp_label_en)
        form.addRow(self._lbl_desc_es_row, self._inp_desc_es)
        form.addRow(self._lbl_desc_en_row, self._inp_desc_en)
        form.addRow("", self._cnt_label)

        for w in (self._inp_label_es, self._inp_label_en):
            w.editingFinished.connect(self._save_metadata)
        for t in (self._inp_desc_es, self._inp_desc_en):
            t.textChanged.connect(self._save_metadata)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self.retranslate()

    def _wire(self) -> None:
        self._bridge.config_reloaded.connect(self._reload)

    # ---------- list ----------

    def _reload(self) -> None:
        self._suppress = True
        try:
            cf = self._orch.config
            self._list.clear()
            for p in cf.profiles:
                item = QListWidgetItem(f"{p.id}  —  {p.label_es or ''}")
                item.setData(Qt.UserRole, p.id)
                self._list.addItem(item)
            if self._list.count() > 0:
                target = self._editing_id or self._orch.profiles.active_id
                for i in range(self._list.count()):
                    if self._list.item(i).data(Qt.UserRole) == target:
                        self._list.setCurrentRow(i)
                        break
                else:
                    self._list.setCurrentRow(0)
            self._refresh_right()
        finally:
            self._suppress = False

    def _selected_id(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_select(self) -> None:
        if self._suppress:
            return
        self._editing_id = self._selected_id()
        self._refresh_right()

    def _refresh_right(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        cf = self._orch.config
        try:
            p = cf.get_profile(pid)
        except KeyError:
            return
        self._suppress = True
        try:
            self._lbl_id.setText(p.id)
            self._inp_label_es.setText(p.label_es or "")
            self._inp_label_en.setText(p.label_en or "")
            self._inp_desc_es.setPlainText(p.description_es or "")
            self._inp_desc_en.setPlainText(p.description_en or "")
            self._cnt_label.setText(tr("profiles.commands_count", n=len(p.commands)))
        finally:
            self._suppress = False

    # ---------- ops ----------

    def _on_new(self) -> None:
        new_id, ok = QInputDialog.getText(self, tr("profiles.new"), "ID:")
        if not ok or not new_id.strip():
            return
        new_id = new_id.strip()
        if not cfgmod.ID_RE.match(new_id):
            QMessageBox.warning(self, tr("common.error"), "id inválido")
            return
        cf = self._orch.config
        if any(p.id == new_id for p in cf.profiles):
            QMessageBox.warning(self, tr("common.error"), tr("commands.error.duplicate_id"))
            return
        new_profile = {
            "id": new_id,
            "label_es": new_id.title(),
            "label_en": new_id.title(),
            "commands": [
                {"id": "placeholder", "phrases_es": ["placeholder"], "keys": ["a"]}
            ],
        }
        self._apply_profiles_change([*[p.model_dump() for p in cf.profiles], new_profile])
        self._editing_id = new_id

    def _on_dup(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        cf = self._orch.config
        src = cf.get_profile(pid)
        new_id = f"{pid}_copy"
        n = 1
        while any(p.id == new_id for p in cf.profiles):
            n += 1
            new_id = f"{pid}_copy{n}"
        new_dict = src.model_dump()
        new_dict["id"] = new_id
        if new_dict.get("label_es"):
            new_dict["label_es"] = f"{new_dict['label_es']} (copy)"
        if new_dict.get("label_en"):
            new_dict["label_en"] = f"{new_dict['label_en']} (copy)"
        new_profiles = [p.model_dump() for p in cf.profiles]
        new_profiles.append(new_dict)
        self._apply_profiles_change(new_profiles)

    def _on_delete(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        cf = self._orch.config
        if len(cf.profiles) <= 1:
            QMessageBox.warning(self, tr("common.error"), tr("profiles.error.at_least_one"))
            return
        if QMessageBox.question(self, tr("common.confirm"), tr("profiles.confirm_delete", id=pid)) != QMessageBox.Yes:
            return
        new_profiles = [p.model_dump() for p in cf.profiles if p.id != pid]
        # Si el active_profile era este, fallback al primero restante.
        settings = cf.settings.model_dump()
        if settings.get("active_profile") == pid:
            settings["active_profile"] = new_profiles[0]["id"]
        self._apply_profiles_change(new_profiles, settings)

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("profiles.import"), "", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), str(e))
            return
        if not isinstance(raw, dict) or "id" not in raw or "commands" not in raw:
            QMessageBox.warning(self, tr("common.error"), "perfil inválido: faltan campos id/commands")
            return
        cf = self._orch.config
        if any(p.id == raw["id"] for p in cf.profiles):
            QMessageBox.warning(self, tr("common.error"), tr("commands.error.duplicate_id"))
            return
        # SEGURIDAD (defense-in-depth): un perfil compartido inyecta teclas al SO.
        # Mostrar las teclas distintas antes de aplicar deja al usuario ver qué va
        # a ejecutar. La validación de keypress ya bloquea combos peligrosos, pero
        # esto hace visible el contenido de un perfil de origen no confiable.
        combos = _collect_combos_from_raw_profile(raw)
        preview = ", ".join(sorted(combos)[:30]) or "(ninguna)"
        n_cmds = len(raw.get("commands", []))
        confirm = QMessageBox.question(
            self,
            tr("profiles.import"),
            f"Perfil '{raw['id']}' — {n_cmds} comandos.\n\n"
            f"Teclas que puede enviar:\n{preview}\n\n"
            "Importá solo perfiles de fuentes en las que confiás. ¿Continuar?",
        )
        if confirm != QMessageBox.Yes:
            return
        new_profiles = [p.model_dump() for p in cf.profiles]
        new_profiles.append(raw)
        self._apply_profiles_change(new_profiles)

    def _on_export(self) -> None:
        pid = self._selected_id()
        if pid is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("profiles.export"), f"{pid}.yaml", "YAML (*.yaml)")
        if not path:
            return
        prof = self._orch.config.get_profile(pid).model_dump()
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(prof, f, sort_keys=False, allow_unicode=True)
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), str(e))

    def _save_metadata(self) -> None:
        if self._suppress:
            return
        pid = self._selected_id()
        if pid is None:
            return
        cf = self._orch.config
        new_profiles = []
        for p in cf.profiles:
            d = p.model_dump()
            if p.id == pid:
                d["label_es"] = self._inp_label_es.text() or None
                d["label_en"] = self._inp_label_en.text() or None
                d["description_es"] = self._inp_desc_es.toPlainText() or None
                d["description_en"] = self._inp_desc_en.toPlainText() or None
            new_profiles.append(d)
        self._apply_profiles_change(new_profiles)

    # ---------- apply ----------

    def _apply_profiles_change(
        self,
        new_profiles: list[dict[str, Any]],
        new_settings: dict[str, Any] | None = None,
    ) -> None:
        cf = self._orch.config
        settings = new_settings or cf.settings.model_dump()
        new_dump = {"version": 2, "settings": settings, "profiles": new_profiles}
        try:
            new_cf = cfgmod.CommandsFileV2.model_validate(new_dump)
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), str(e))
            logger.warning("profiles_change_invalid err=%s", e)
            return
        try:
            cfgmod.save_atomic(new_cf, self._orch.config_path)
        except Exception:
            logger.exception("profiles_save_failed")
            return
        self._orch.reload_config()

    # ---------- i18n ----------

    def retranslate(self) -> None:
        self._btn_new.setText(tr("profiles.new"))
        self._btn_dup.setText(tr("profiles.duplicate"))
        self._btn_del.setText(tr("profiles.delete"))
        self._btn_imp.setText(tr("profiles.import"))
        self._btn_exp.setText(tr("profiles.export"))
        self._right_box.setTitle(tr("sidebar.profiles"))
