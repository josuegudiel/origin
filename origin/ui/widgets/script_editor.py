"""ScriptEditorDialog — editor visual del DSL de steps por comando.

MVP funcional: lista plana de steps editables tipo-por-tipo via panel inferior.
Para `if` / `repeat` con sub-steps, la UX recomendada es editar el YAML directo
en `%APPDATA%/Origin/commands.yaml` (más expresivo y menos error-prone que un
sub-editor anidado en Qt). El editor permite crear / borrar / reordenar los
step types **planos** (key, wait, say, say_key, set, goto, label) que cubren el
80% de los casos prácticos.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...engine.config import (
    GotoStep,
    IfStep,
    KeyStep,
    LabelStep,
    RepeatStep,
    SayKeyStep,
    SayStep,
    SetStep,
    WaitStep,
)
from ..i18n.tr import tr

STEP_TYPES = ["key", "wait", "say", "say_key", "set", "goto", "label"]


def _step_label(s: Any) -> str:
    if isinstance(s, KeyStep):
        suffix = f" hold {s.hold_ms}ms" if s.hold_ms else ""
        return f"[key]  {s.combo}{suffix}"
    if isinstance(s, WaitStep):
        return f"[wait] {s.ms} ms"
    if isinstance(s, SayStep):
        t = s.text_es or s.text_en or s.text or ""
        return f"[say]  \"{t[:50]}\""
    if isinstance(s, SayKeyStep):
        return f"[say_key] {s.key}"
    if isinstance(s, SetStep):
        return f"[set]  {s.var} = {s.value}"
    if isinstance(s, IfStep):
        return f"[if]   {s.cond}   (sub-steps no editables en MVP)"
    if isinstance(s, GotoStep):
        return f"[goto] {s.label}"
    if isinstance(s, LabelStep):
        return f"[label] {s.name}"
    if isinstance(s, RepeatStep):
        return f"[repeat × {s.times}]  (sub-steps no editables en MVP)"
    return "[unknown]"


class ScriptEditorDialog(QDialog):
    def __init__(self, steps: list[Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("script.title"))
        self.resize(720, 520)
        self._steps: list[Any] = list(steps or [])
        self._build_ui()
        self._refresh_list()

    @property
    def result_steps(self) -> list[Any]:
        return self._steps

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # Lista de steps
        left = QVBoxLayout()
        body.addLayout(left, 2)
        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._on_select)
        left.addWidget(self._list, 1)
        bar = QHBoxLayout()
        self._btn_add = QPushButton(tr("script.add_step"))
        self._btn_add.clicked.connect(self._on_add)
        self._btn_del = QPushButton(tr("script.delete_step"))
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_up = QPushButton("↑")
        self._btn_up.clicked.connect(lambda: self._move(-1))
        self._btn_down = QPushButton("↓")
        self._btn_down.clicked.connect(lambda: self._move(+1))
        for b in (self._btn_add, self._btn_del, self._btn_up, self._btn_down):
            bar.addWidget(b)
        left.addLayout(bar)

        # Panel editor del step seleccionado
        right = QVBoxLayout()
        body.addLayout(right, 3)
        self._editor_stack = QStackedWidget()
        right.addWidget(self._editor_stack, 1)
        self._build_editors()

        # Buttons OK/Cancel
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    def _build_editors(self) -> None:
        # Empty
        self._editor_stack.addWidget(QLabel("—"))
        # KeyStep
        w = QWidget(); f = QFormLayout(w)
        self._ed_key_combo = QLineEdit()
        self._ed_key_hold = QSpinBox(); self._ed_key_hold.setRange(0, 10_000)
        f.addRow("combo", self._ed_key_combo)
        f.addRow("hold_ms (0=tap)", self._ed_key_hold)
        self._ed_key_combo.editingFinished.connect(self._save_current)
        self._ed_key_hold.valueChanged.connect(lambda _v: self._save_current())
        self._editor_stack.addWidget(w)
        # WaitStep
        w = QWidget(); f = QFormLayout(w)
        self._ed_wait_ms = QSpinBox(); self._ed_wait_ms.setRange(0, 30_000)
        f.addRow("ms", self._ed_wait_ms)
        self._ed_wait_ms.valueChanged.connect(lambda _v: self._save_current())
        self._editor_stack.addWidget(w)
        # SayStep
        w = QWidget(); f = QFormLayout(w)
        self._ed_say_es = QLineEdit()
        self._ed_say_en = QLineEdit()
        f.addRow("text_es", self._ed_say_es)
        f.addRow("text_en", self._ed_say_en)
        self._ed_say_es.editingFinished.connect(self._save_current)
        self._ed_say_en.editingFinished.connect(self._save_current)
        self._editor_stack.addWidget(w)
        # SayKeyStep
        w = QWidget(); f = QFormLayout(w)
        self._ed_saykey = QLineEdit()
        f.addRow("key", self._ed_saykey)
        self._ed_saykey.editingFinished.connect(self._save_current)
        self._editor_stack.addWidget(w)
        # SetStep
        w = QWidget(); f = QFormLayout(w)
        self._ed_set_var = QLineEdit()
        self._ed_set_val = QLineEdit()
        f.addRow("var", self._ed_set_var)
        f.addRow("value", self._ed_set_val)
        self._ed_set_var.editingFinished.connect(self._save_current)
        self._ed_set_val.editingFinished.connect(self._save_current)
        self._editor_stack.addWidget(w)
        # GotoStep
        w = QWidget(); f = QFormLayout(w)
        self._ed_goto = QLineEdit()
        f.addRow("label", self._ed_goto)
        self._ed_goto.editingFinished.connect(self._save_current)
        self._editor_stack.addWidget(w)
        # LabelStep
        w = QWidget(); f = QFormLayout(w)
        self._ed_label_name = QLineEdit()
        f.addRow("name", self._ed_label_name)
        self._ed_label_name.editingFinished.connect(self._save_current)
        self._editor_stack.addWidget(w)
        # IfStep / RepeatStep — readonly noticia
        for kind in ("if", "repeat"):
            w = QWidget(); v = QVBoxLayout(w)
            v.addWidget(QLabel(f"Step '{kind}' tiene sub-steps anidados. Editalo desde el YAML directamente."))
            self._editor_stack.addWidget(w)

    # ---------------------------------------------------------------- ops

    def _refresh_list(self) -> None:
        self._list.clear()
        for i, s in enumerate(self._steps):
            item = QListWidgetItem(f"{i:02d}  {_step_label(s)}")
            item.setData(Qt.UserRole, i)
            self._list.addItem(item)
        if self._steps and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)

    def _selected_index(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.UserRole))

    def _on_select(self) -> None:
        idx = self._selected_index()
        if idx is None or not (0 <= idx < len(self._steps)):
            self._editor_stack.setCurrentIndex(0)
            return
        s = self._steps[idx]
        if isinstance(s, KeyStep):
            self._editor_stack.setCurrentIndex(1)
            self._ed_key_combo.setText(s.combo)
            self._ed_key_hold.setValue(s.hold_ms or 0)
        elif isinstance(s, WaitStep):
            self._editor_stack.setCurrentIndex(2)
            self._ed_wait_ms.setValue(s.ms)
        elif isinstance(s, SayStep):
            self._editor_stack.setCurrentIndex(3)
            self._ed_say_es.setText(s.text_es or "")
            self._ed_say_en.setText(s.text_en or "")
        elif isinstance(s, SayKeyStep):
            self._editor_stack.setCurrentIndex(4)
            self._ed_saykey.setText(s.key)
        elif isinstance(s, SetStep):
            self._editor_stack.setCurrentIndex(5)
            self._ed_set_var.setText(s.var)
            self._ed_set_val.setText(s.value)
        elif isinstance(s, GotoStep):
            self._editor_stack.setCurrentIndex(6)
            self._ed_goto.setText(s.label)
        elif isinstance(s, LabelStep):
            self._editor_stack.setCurrentIndex(7)
            self._ed_label_name.setText(s.name)
        elif isinstance(s, IfStep):
            self._editor_stack.setCurrentIndex(8)
        elif isinstance(s, RepeatStep):
            self._editor_stack.setCurrentIndex(9)
        else:
            self._editor_stack.setCurrentIndex(0)

    def _save_current(self) -> None:
        idx = self._selected_index()
        if idx is None or not (0 <= idx < len(self._steps)):
            return
        s = self._steps[idx]
        try:
            if isinstance(s, KeyStep):
                hold = self._ed_key_hold.value() or None
                new_s = KeyStep(combo=self._ed_key_combo.text(), hold_ms=hold)
            elif isinstance(s, WaitStep):
                new_s = WaitStep(ms=self._ed_wait_ms.value())
            elif isinstance(s, SayStep):
                new_s = SayStep(
                    text_es=self._ed_say_es.text() or None,
                    text_en=self._ed_say_en.text() or None,
                    text=None,
                )
            elif isinstance(s, SayKeyStep):
                new_s = SayKeyStep(key=self._ed_saykey.text() or "tts.unknown")
            elif isinstance(s, SetStep):
                new_s = SetStep(var=self._ed_set_var.text(), value=self._ed_set_val.text())
            elif isinstance(s, GotoStep):
                new_s = GotoStep(label=self._ed_goto.text())
            elif isinstance(s, LabelStep):
                new_s = LabelStep(name=self._ed_label_name.text())
            else:
                return  # if/repeat readonly
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), str(e))
            return
        self._steps[idx] = new_s
        # Solo redibujar la fila editada — cambio de selección rompería el flujo de tipeo.
        self._list.item(idx).setText(f"{idx:02d}  {_step_label(new_s)}")

    def _on_add(self) -> None:
        kind, ok = QInputDialog.getItem(self, tr("script.add_step"), "type:", STEP_TYPES, 0, False)
        if not ok:
            return
        try:
            if kind == "key":
                new_s = KeyStep(combo="a")
            elif kind == "wait":
                new_s = WaitStep(ms=100)
            elif kind == "say":
                new_s = SayStep(text_es="…", text_en="…")
            elif kind == "say_key":
                new_s = SayKeyStep(key="tts.placeholder")
            elif kind == "set":
                new_s = SetStep(var="my_var", value="value")
            elif kind == "goto":
                new_s = GotoStep(label="end")
            elif kind == "label":
                new_s = LabelStep(name="end")
            else:
                return
        except Exception as e:
            QMessageBox.warning(self, tr("common.error"), str(e))
            return
        insert_at = (self._selected_index() + 1) if self._selected_index() is not None else len(self._steps)
        self._steps.insert(insert_at, new_s)
        self._refresh_list()
        self._list.setCurrentRow(insert_at)

    def _on_delete(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        del self._steps[idx]
        self._refresh_list()

    def _move(self, delta: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + delta
        if not (0 <= new_idx < len(self._steps)):
            return
        self._steps[idx], self._steps[new_idx] = self._steps[new_idx], self._steps[idx]
        self._refresh_list()
        self._list.setCurrentRow(new_idx)
