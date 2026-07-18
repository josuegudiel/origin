"""Página Ajustes — todas las preferencias del bloque `settings` del commands.yaml."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...engine import audio as audiomod
from ...engine import autostart_windows, keypress
from ...engine.llm import OllamaClient
from ...engine.paths import bundled_voices_dir, default_paths
from ...engine.runtime import Orchestrator
from ..engine_bridge import EngineBridge
from ..i18n.tr import register_retranslatable, tr
from ..widgets.fuzz_slider import FuzzSlider
from ..widgets.key_capture import KeyCapture

logger = logging.getLogger(__name__)


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_SIZE_HINT = {"tiny": "~75 MB", "base": "~145 MB", "small": "~485 MB", "medium": "~1.5 GB", "large-v3": "~3 GB"}
DEVICES = ["auto", "cpu", "cuda"]
COMPUTE_TYPES = ["auto", "int8", "int8_float16", "float16", "float32"]
SAMPLE_RATES = [16000, 44100, 48000]
LOG_FORMATS = ["pretty", "json"]
UI_LANGS = ["es", "en"]
THEMES = ["system", "light", "dark"]


def _cuda_available() -> bool:
    try:
        import ctranslate2  # type: ignore[import-untyped]

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class SettingsPage(QWidget):
    def __init__(self, orch: Orchestrator, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._orch = orch
        self._bridge = bridge
        self._build_ui()
        self._populate_from_settings()
        register_retranslatable(self.retranslate)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll, 1)
        page = QWidget()
        scroll.setWidget(page)
        root = QVBoxLayout(page)

        # ----- Hotkeys -----
        self._gb_hotkeys = QGroupBox()
        f = QFormLayout(self._gb_hotkeys)
        self._ptt = KeyCapture(initial=self._orch.config.settings.ptt_key, capture_combo=False, validate_cb=keypress.validate)
        self._ptt.keyCaptured.connect(lambda v: self._apply("ptt_key", v))
        self._lbl_ptt = QLabel()
        f.addRow(self._lbl_ptt, self._ptt)
        self._switch = KeyCapture(
            initial=self._orch.config.settings.profile_switch_hotkey,
            capture_combo=True,
            validate_cb=keypress.validate,
        )
        self._switch.keyCaptured.connect(lambda v: self._apply("profile_switch_hotkey", v))
        self._lbl_switch = QLabel()
        f.addRow(self._lbl_switch, self._switch)
        root.addWidget(self._gb_hotkeys)

        # ----- Whisper -----
        self._gb_whisper = QGroupBox()
        f = QFormLayout(self._gb_whisper)
        self._cb_model = QComboBox()
        for m in WHISPER_MODELS:
            self._cb_model.addItem(f"{m}  ({MODEL_SIZE_HINT[m]})", m)
        self._cb_model.currentIndexChanged.connect(
            lambda _i: self._apply("whisper_model", self._cb_model.currentData())
        )
        self._lbl_model = QLabel()
        f.addRow(self._lbl_model, self._cb_model)

        self._cb_device = QComboBox()
        for d in DEVICES:
            self._cb_device.addItem(d, d)
        if not _cuda_available():
            idx = self._cb_device.findData("cuda")
            if idx >= 0:
                item = self._cb_device.model().item(idx)
                if item:
                    item.setEnabled(False)
        self._cb_device.currentIndexChanged.connect(
            lambda _i: self._apply("whisper_device", self._cb_device.currentData())
        )
        self._lbl_device = QLabel()
        f.addRow(self._lbl_device, self._cb_device)

        self._cb_compute = QComboBox()
        for c in COMPUTE_TYPES:
            self._cb_compute.addItem(c, c)
        self._cb_compute.currentIndexChanged.connect(
            lambda _i: self._apply("whisper_compute_type", self._cb_compute.currentData())
        )
        self._lbl_compute = QLabel()
        f.addRow(self._lbl_compute, self._cb_compute)

        root.addWidget(self._gb_whisper)

        # ----- Audio -----
        self._gb_audio = QGroupBox()
        f = QFormLayout(self._gb_audio)
        mic_row = QHBoxLayout()
        self._cb_mic = QComboBox()
        self._refresh_mics()
        self._cb_mic.currentIndexChanged.connect(
            lambda _i: self._apply("mic_device", self._cb_mic.currentData())
        )
        self._btn_refresh_mics = QPushButton()
        self._btn_refresh_mics.clicked.connect(self._refresh_mics)
        mic_row.addWidget(self._cb_mic, 1)
        mic_row.addWidget(self._btn_refresh_mics)
        self._lbl_mic = QLabel()
        f.addRow(self._lbl_mic, mic_row)

        self._cb_sr = QComboBox()
        for sr in SAMPLE_RATES:
            self._cb_sr.addItem(str(sr), sr)
        self._cb_sr.currentIndexChanged.connect(
            lambda _i: self._apply("sample_rate", self._cb_sr.currentData())
        )
        self._lbl_sr = QLabel()
        f.addRow(self._lbl_sr, self._cb_sr)

        self._sp_maxrec = QSpinBox()
        self._sp_maxrec.setRange(1, 60)
        self._sp_maxrec.valueChanged.connect(lambda v: self._apply("max_record_seconds", int(v)))
        self._lbl_maxrec = QLabel()
        f.addRow(self._lbl_maxrec, self._sp_maxrec)

        root.addWidget(self._gb_audio)

        # ----- Matching -----
        self._gb_match = QGroupBox()
        f = QFormLayout(self._gb_match)
        self._fuzz = FuzzSlider(initial=self._orch.config.settings.fuzz_threshold, preview_cb=self._preview_match)
        self._fuzz.valueChanged.connect(lambda v: self._apply("fuzz_threshold", int(v)))
        self._lbl_fuzz = QLabel()
        f.addRow(self._lbl_fuzz, self._fuzz)
        self._sp_delay = QSpinBox()
        self._sp_delay.setRange(0, 500)
        self._sp_delay.valueChanged.connect(lambda v: self._apply("inter_key_delay_ms", int(v)))
        self._lbl_delay = QLabel()
        f.addRow(self._lbl_delay, self._sp_delay)
        root.addWidget(self._gb_match)

        # ----- UI -----
        self._gb_ui = QGroupBox()
        f = QFormLayout(self._gb_ui)
        self._cb_ui_lang = QComboBox()
        for lang in UI_LANGS:
            self._cb_ui_lang.addItem(lang.upper(), lang)
        self._cb_ui_lang.currentIndexChanged.connect(
            lambda _i: self._apply("ui_language", self._cb_ui_lang.currentData())
        )
        self._lbl_ui_lang = QLabel()
        f.addRow(self._lbl_ui_lang, self._cb_ui_lang)
        self._cb_theme = QComboBox()
        for t in THEMES:
            self._cb_theme.addItem(t, t)
        self._cb_theme.currentIndexChanged.connect(
            lambda _i: self._apply("theme", self._cb_theme.currentData())
        )
        self._lbl_theme = QLabel()
        f.addRow(self._lbl_theme, self._cb_theme)
        root.addWidget(self._gb_ui)

        # ----- Startup -----
        self._gb_startup = QGroupBox()
        f = QFormLayout(self._gb_startup)
        self._chk_autostart = QCheckBox()
        self._chk_autostart.toggled.connect(self._on_autostart_toggled)
        self._chk_minimized = QCheckBox()
        self._chk_minimized.toggled.connect(lambda v: self._apply("start_minimized", bool(v)))
        if not autostart_windows.is_supported():
            self._chk_autostart.setEnabled(False)
            self._chk_autostart.setToolTip(tr("settings.autostart_not_supported"))
        self._lbl_autostart = QLabel()
        self._lbl_minimized = QLabel()
        f.addRow(self._lbl_autostart, self._chk_autostart)
        f.addRow(self._lbl_minimized, self._chk_minimized)
        root.addWidget(self._gb_startup)

        # ----- Logs -----
        self._gb_logs = QGroupBox()
        f = QFormLayout(self._gb_logs)
        self._cb_log = QComboBox()
        for lf in LOG_FORMATS:
            self._cb_log.addItem(lf, lf)
        self._cb_log.currentIndexChanged.connect(
            lambda _i: self._apply("log_format", self._cb_log.currentData())
        )
        self._lbl_log = QLabel()
        f.addRow(self._lbl_log, self._cb_log)
        self._btn_open_logs = QPushButton()
        self._btn_open_logs.clicked.connect(self._open_logs_folder)
        f.addRow("", self._btn_open_logs)
        root.addWidget(self._gb_logs)

        # ----- TTS -----
        self._gb_tts = QGroupBox()
        f = QFormLayout(self._gb_tts)
        self._chk_tts = QCheckBox()
        self._chk_tts.toggled.connect(lambda v: self._apply_sub("tts", {"enabled": bool(v)}))
        self._cb_voice_es = QComboBox()
        self._cb_voice_en = QComboBox()
        self._cb_voice_es.currentIndexChanged.connect(
            lambda _i: self._apply_sub("tts", {"voice_es": self._cb_voice_es.currentData() or ""})
        )
        self._cb_voice_en.currentIndexChanged.connect(
            lambda _i: self._apply_sub("tts", {"voice_en": self._cb_voice_en.currentData() or ""})
        )
        self._btn_tts_refresh = QPushButton()
        self._btn_tts_refresh.clicked.connect(self._refresh_voices)
        self._sp_tts_speed = QDoubleSpinBox()
        self._sp_tts_speed.setRange(0.5, 2.0)
        self._sp_tts_speed.setSingleStep(0.05)
        self._sp_tts_speed.valueChanged.connect(lambda v: self._apply_sub("tts", {"speed": float(v)}))
        self._sp_tts_volume = QDoubleSpinBox()
        self._sp_tts_volume.setRange(0.0, 1.5)
        self._sp_tts_volume.setSingleStep(0.1)
        self._sp_tts_volume.valueChanged.connect(lambda v: self._apply_sub("tts", {"volume": float(v)}))
        self._chk_tts_default = QCheckBox()
        self._chk_tts_default.toggled.connect(
            lambda v: self._apply_sub("tts", {"default_response_when_no_say": bool(v)})
        )
        self._chk_tts_cancel = QCheckBox()
        self._chk_tts_cancel.toggled.connect(
            lambda v: self._apply_sub("tts", {"cancel_on_ptt": bool(v)})
        )
        self._btn_tts_test = QPushButton()
        self._btn_tts_test.clicked.connect(self._on_tts_test)
        self._lbl_tts_enabled = QLabel()
        self._lbl_tts_voice_es = QLabel()
        self._lbl_tts_voice_en = QLabel()
        self._lbl_tts_speed = QLabel()
        self._lbl_tts_volume = QLabel()
        self._lbl_tts_default = QLabel()
        self._lbl_tts_cancel = QLabel()
        f.addRow(self._lbl_tts_enabled, self._chk_tts)
        f.addRow(self._lbl_tts_voice_es, self._cb_voice_es)
        f.addRow(self._lbl_tts_voice_en, self._cb_voice_en)
        f.addRow("", self._btn_tts_refresh)
        f.addRow(self._lbl_tts_speed, self._sp_tts_speed)
        f.addRow(self._lbl_tts_volume, self._sp_tts_volume)
        f.addRow(self._lbl_tts_default, self._chk_tts_default)
        f.addRow(self._lbl_tts_cancel, self._chk_tts_cancel)
        f.addRow("", self._btn_tts_test)
        root.addWidget(self._gb_tts)

        # ----- HOTAS -----
        self._gb_hotas = QGroupBox()
        f = QFormLayout(self._gb_hotas)
        self._chk_hotas = QCheckBox()
        self._chk_hotas.toggled.connect(lambda v: self._apply_sub("hotas", {"enabled": bool(v)}))
        self._inp_hotas_binding = QLineEdit()
        self._inp_hotas_binding.setReadOnly(True)
        self._btn_hotas_capture = QPushButton()
        self._btn_hotas_capture.clicked.connect(self._on_hotas_capture)
        self._sp_hotas_hz = QSpinBox()
        self._sp_hotas_hz.setRange(10, 240)
        self._sp_hotas_hz.valueChanged.connect(lambda v: self._apply_sub("hotas", {"poll_hz": int(v)}))
        self._lbl_hotas_enabled = QLabel()
        self._lbl_hotas_binding = QLabel()
        self._lbl_hotas_hz = QLabel()
        f.addRow(self._lbl_hotas_enabled, self._chk_hotas)
        binding_row = QHBoxLayout()
        binding_row.addWidget(self._inp_hotas_binding, 1)
        binding_row.addWidget(self._btn_hotas_capture)
        f.addRow(self._lbl_hotas_binding, binding_row)
        f.addRow(self._lbl_hotas_hz, self._sp_hotas_hz)
        root.addWidget(self._gb_hotas)

        # ----- LLM -----
        self._gb_llm = QGroupBox()
        f = QFormLayout(self._gb_llm)
        self._chk_llm = QCheckBox()
        self._chk_llm.toggled.connect(lambda v: self._apply_sub("llm", {"enabled": bool(v)}))
        self._inp_llm_url = QLineEdit()
        self._inp_llm_url.editingFinished.connect(
            lambda: self._apply_sub("llm", {"base_url": self._inp_llm_url.text()})
        )
        self._inp_llm_model = QLineEdit()
        self._inp_llm_model.editingFinished.connect(
            lambda: self._apply_sub("llm", {"model": self._inp_llm_model.text()})
        )
        self._sp_llm_timeout = QSpinBox()
        self._sp_llm_timeout.setRange(500, 60000)
        self._sp_llm_timeout.setSingleStep(500)
        self._sp_llm_timeout.valueChanged.connect(lambda v: self._apply_sub("llm", {"timeout_ms": int(v)}))
        self._sp_llm_floor = QSpinBox()
        self._sp_llm_floor.setRange(0, 100)
        self._sp_llm_floor.valueChanged.connect(lambda v: self._apply_sub("llm", {"floor_score": int(v)}))
        self._sp_llm_temp = QDoubleSpinBox()
        self._sp_llm_temp.setRange(0.0, 2.0)
        self._sp_llm_temp.setSingleStep(0.05)
        self._sp_llm_temp.valueChanged.connect(lambda v: self._apply_sub("llm", {"temperature": float(v)}))
        self._btn_llm_test = QPushButton()
        self._btn_llm_test.clicked.connect(self._on_llm_test)
        self._lbl_llm_enabled = QLabel()
        self._lbl_llm_url = QLabel()
        self._lbl_llm_model = QLabel()
        self._lbl_llm_timeout = QLabel()
        self._lbl_llm_floor = QLabel()
        self._lbl_llm_temp = QLabel()
        f.addRow(self._lbl_llm_enabled, self._chk_llm)
        f.addRow(self._lbl_llm_url, self._inp_llm_url)
        f.addRow(self._lbl_llm_model, self._inp_llm_model)
        f.addRow(self._lbl_llm_timeout, self._sp_llm_timeout)
        f.addRow(self._lbl_llm_floor, self._sp_llm_floor)
        f.addRow(self._lbl_llm_temp, self._sp_llm_temp)
        f.addRow("", self._btn_llm_test)
        root.addWidget(self._gb_llm)

        self._refresh_voices()
        root.addStretch(1)
        self.retranslate()

    # ---------------------------------------------------------------- populate

    def _populate_from_settings(self) -> None:
        s = self._orch.config.settings
        # Bloqueamos signals para no disparar apply en cascada al setear UI.
        for w in (self._cb_model, self._cb_device, self._cb_compute, self._cb_mic, self._cb_sr,
                  self._cb_ui_lang, self._cb_theme, self._cb_log, self._sp_maxrec, self._sp_delay,
                  self._chk_autostart, self._chk_minimized):
            w.blockSignals(True)
        try:
            self._cb_model.setCurrentIndex(self._cb_model.findData(s.whisper_model))
            self._cb_device.setCurrentIndex(self._cb_device.findData(s.whisper_device))
            self._cb_compute.setCurrentIndex(self._cb_compute.findData(s.whisper_compute_type))
            idx = self._cb_mic.findData(s.mic_device)
            if idx >= 0:
                self._cb_mic.setCurrentIndex(idx)
            self._cb_sr.setCurrentIndex(self._cb_sr.findData(s.sample_rate))
            self._sp_maxrec.setValue(s.max_record_seconds)
            self._fuzz._slider.setValue(s.fuzz_threshold)  # noqa: SLF001
            self._sp_delay.setValue(s.inter_key_delay_ms)
            self._cb_ui_lang.setCurrentIndex(self._cb_ui_lang.findData(s.ui_language))
            self._cb_theme.setCurrentIndex(self._cb_theme.findData(s.theme))
            self._cb_log.setCurrentIndex(self._cb_log.findData(s.log_format))
            self._chk_autostart.setChecked(s.autostart_windows)
            self._chk_minimized.setChecked(s.start_minimized)
            # ----- v0.3 -----
            tts = s.tts
            for w in (self._chk_tts, self._sp_tts_speed, self._sp_tts_volume,
                      self._chk_tts_default, self._chk_tts_cancel,
                      self._chk_hotas, self._sp_hotas_hz,
                      self._chk_llm, self._inp_llm_url, self._inp_llm_model,
                      self._sp_llm_timeout, self._sp_llm_floor, self._sp_llm_temp,
                      self._inp_hotas_binding):
                w.blockSignals(True)
            self._chk_tts.setChecked(tts.enabled)
            self._sp_tts_speed.setValue(tts.speed)
            self._sp_tts_volume.setValue(tts.volume)
            self._chk_tts_default.setChecked(tts.default_response_when_no_say)
            self._chk_tts_cancel.setChecked(tts.cancel_on_ptt)
            hot = s.hotas
            self._chk_hotas.setChecked(hot.enabled)
            self._sp_hotas_hz.setValue(hot.poll_hz)
            self._inp_hotas_binding.setText(hot.button_binding or "")
            llm = s.llm
            self._chk_llm.setChecked(llm.enabled)
            self._inp_llm_url.setText(llm.base_url)
            self._inp_llm_model.setText(llm.model)
            self._sp_llm_timeout.setValue(llm.timeout_ms)
            self._sp_llm_floor.setValue(llm.floor_score)
            self._sp_llm_temp.setValue(llm.temperature)
        finally:
            for w in (self._cb_model, self._cb_device, self._cb_compute, self._cb_mic, self._cb_sr,
                      self._cb_ui_lang, self._cb_theme, self._cb_log, self._sp_maxrec, self._sp_delay,
                      self._chk_autostart, self._chk_minimized,
                      self._chk_tts, self._sp_tts_speed, self._sp_tts_volume,
                      self._chk_tts_default, self._chk_tts_cancel,
                      self._chk_hotas, self._sp_hotas_hz,
                      self._chk_llm, self._inp_llm_url, self._inp_llm_model,
                      self._sp_llm_timeout, self._sp_llm_floor, self._sp_llm_temp,
                      self._inp_hotas_binding):
                w.blockSignals(False)

    def _refresh_mics(self) -> None:
        s = self._orch.config.settings
        self._cb_mic.blockSignals(True)
        self._cb_mic.clear()
        self._cb_mic.addItem("(default)", None)
        try:
            for d in audiomod.list_input_devices():
                tag = " *" if d.get("default") else ""
                self._cb_mic.addItem(f"{d['index']}: {d['name']}{tag}", d["index"])
        except Exception:
            logger.exception("list_mics_failed")
        idx = self._cb_mic.findData(s.mic_device)
        if idx >= 0:
            self._cb_mic.setCurrentIndex(idx)
        self._cb_mic.blockSignals(False)

    def _preview_match(self, text: str) -> list[tuple[str, float]]:
        matcher = self._orch.profiles.matcher()
        results = matcher.preview(text, self._orch.config.settings.active_language, top_n=8)
        return [(f"{cmd.id}  ←  {phrase}", score) for cmd, phrase, score in results]

    # ---------------------------------------------------------------- apply

    def _apply(self, key: str, value: Any) -> None:
        try:
            self._orch.set_setting(**{key: value})
        except Exception as e:
            logger.exception("set_setting_failed key=%s", key)
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, tr("common.error"), str(e))

    def _apply_sub(self, section: str, changes: dict[str, Any]) -> None:
        """Aplica cambios a un sub-bloque de settings (tts/hotas/llm)."""
        try:
            self._orch.set_setting(**{section: changes})
        except Exception as e:
            logger.exception("set_subsetting_failed section=%s", section)
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, tr("common.error"), str(e))

    def _refresh_voices(self) -> None:
        """Pobla los dropdowns de voces TTS desde bundled + user dirs."""
        from PySide6.QtCore import QSignalBlocker

        voices: dict[str, Path] = {}
        for d in (bundled_voices_dir(), default_paths().voices_dir):
            if d is None or not d.exists():
                continue
            for onnx in d.glob("*.onnx"):
                if (onnx.parent / f"{onnx.stem}.onnx.json").exists():
                    voices[onnx.stem] = onnx
        s = self._orch.config.settings.tts
        for combo, current in (
            (self._cb_voice_es, s.voice_es),
            (self._cb_voice_en, s.voice_en),
        ):
            with QSignalBlocker(combo):
                combo.clear()
                if not voices:
                    combo.addItem(tr("settings.tts.no_voices"), "")
                else:
                    for stem in sorted(voices):
                        combo.addItem(stem, stem)
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

    def _on_tts_test(self) -> None:
        from PySide6.QtCore import QObject, QThread, Signal

        class Worker(QObject):
            done = Signal()

            def __init__(self, orch, lang):
                super().__init__()
                self._orch = orch
                self._lang = lang

            def run(self):
                if self._orch._tts is not None:  # noqa: SLF001
                    text_es = "Hola capitán, prueba de voz."
                    text_en = "Hello captain, voice test."
                    self._orch._tts.say(  # noqa: SLF001
                        text_en if self._lang == "en" else text_es, self._lang,
                        speed=self._orch.config.settings.tts.speed,
                        volume=self._orch.config.settings.tts.volume,
                    )
                self.done.emit()

        lang = self._orch.config.settings.active_language
        self._tts_thread = QThread(self)
        self._tts_worker = Worker(self._orch, lang)
        self._tts_worker.moveToThread(self._tts_thread)
        self._tts_thread.started.connect(self._tts_worker.run)
        self._tts_worker.done.connect(self._tts_thread.quit)
        self._tts_thread.start()

    def _on_hotas_capture(self) -> None:
        from PySide6.QtCore import QObject, QThread, Signal
        from PySide6.QtWidgets import QMessageBox

        if self._orch._hotas is None:  # noqa: SLF001
            QMessageBox.information(self, tr("common.warning"), tr("settings.hotas.no_devices"))
            return

        original = self._btn_hotas_capture.text()
        self._btn_hotas_capture.setText(tr("settings.hotas.capturing"))
        self._btn_hotas_capture.setEnabled(False)

        class Worker(QObject):
            captured = Signal(str)

            def __init__(self, hotas):
                super().__init__()
                self._hotas = hotas

            def run(self):
                value = self._hotas.capture_next_press(5.0)
                self.captured.emit(value or "")

        self._cap_thread = QThread(self)
        self._cap_worker = Worker(self._orch._hotas)  # noqa: SLF001
        self._cap_worker.moveToThread(self._cap_thread)
        self._cap_thread.started.connect(self._cap_worker.run)

        def on_captured(value: str) -> None:
            self._btn_hotas_capture.setText(original)
            self._btn_hotas_capture.setEnabled(True)
            if value:
                self._inp_hotas_binding.setText(value)
                self._apply_sub("hotas", {"button_binding": value, "enabled": True})

        self._cap_worker.captured.connect(on_captured)
        self._cap_worker.captured.connect(self._cap_thread.quit)
        self._cap_thread.start()

    def _on_llm_test(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        s = self._orch.config.settings.llm
        client = OllamaClient(s.base_url, s.model, s.timeout_ms)
        err = client.preflight()
        if err is None:
            QMessageBox.information(self, tr("settings.llm.test"), tr("settings.llm.preflight_ok"))
        else:
            QMessageBox.warning(self, tr("common.error"), err)

    def _on_autostart_toggled(self, checked: bool) -> None:
        if checked:
            autostart_windows.write_run_key()
        else:
            autostart_windows.remove_run_key()
        self._apply("autostart_windows", bool(checked))

    def _open_logs_folder(self) -> None:
        paths = default_paths()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir)))

    # ---------------------------------------------------------------- i18n

    def retranslate(self) -> None:
        self._gb_hotkeys.setTitle(tr("settings.section.hotkeys"))
        self._gb_whisper.setTitle(tr("settings.section.whisper"))
        self._gb_audio.setTitle(tr("settings.section.audio"))
        self._gb_match.setTitle(tr("settings.section.matching"))
        self._gb_ui.setTitle(tr("settings.section.ui"))
        self._gb_startup.setTitle(tr("settings.section.startup"))
        self._gb_logs.setTitle(tr("settings.section.logs"))
        self._lbl_ptt.setText(tr("settings.ptt_key"))
        self._lbl_switch.setText(tr("settings.profile_switch_hotkey"))
        self._lbl_model.setText(tr("settings.whisper_model"))
        self._lbl_device.setText(tr("settings.whisper_device"))
        self._lbl_compute.setText(tr("settings.whisper_compute_type"))
        self._lbl_mic.setText(tr("settings.mic_device"))
        self._btn_refresh_mics.setText(tr("settings.mic_refresh"))
        self._lbl_sr.setText(tr("settings.sample_rate"))
        self._lbl_maxrec.setText(tr("settings.max_record_seconds"))
        self._lbl_fuzz.setText(tr("settings.fuzz_threshold"))
        self._lbl_delay.setText(tr("settings.inter_key_delay_ms"))
        self._lbl_ui_lang.setText(tr("settings.ui_language"))
        self._lbl_theme.setText(tr("settings.theme"))
        self._lbl_autostart.setText(tr("settings.autostart_windows"))
        self._lbl_minimized.setText(tr("settings.start_minimized"))
        self._lbl_log.setText(tr("settings.log_format"))
        self._btn_open_logs.setText(tr("settings.open_logs_folder"))
        self._fuzz.setPlaceholder(tr("settings.preview_placeholder"))
        # ----- v0.3 -----
        self._gb_tts.setTitle(tr("settings.section.tts"))
        self._lbl_tts_enabled.setText(tr("settings.tts.enabled"))
        self._lbl_tts_voice_es.setText(tr("settings.tts.voice_es"))
        self._lbl_tts_voice_en.setText(tr("settings.tts.voice_en"))
        self._lbl_tts_speed.setText(tr("settings.tts.speed"))
        self._lbl_tts_volume.setText(tr("settings.tts.volume"))
        self._lbl_tts_default.setText(tr("settings.tts.default_response"))
        self._lbl_tts_cancel.setText(tr("settings.tts.cancel_on_ptt"))
        self._btn_tts_refresh.setText(tr("settings.tts.refresh_voices"))
        self._btn_tts_test.setText(tr("settings.tts.test"))
        self._gb_hotas.setTitle(tr("settings.section.hotas"))
        self._lbl_hotas_enabled.setText(tr("settings.hotas.enabled"))
        self._lbl_hotas_binding.setText(tr("settings.hotas.binding"))
        self._btn_hotas_capture.setText(tr("settings.hotas.capture"))
        self._lbl_hotas_hz.setText(tr("settings.hotas.poll_hz"))
        self._gb_llm.setTitle(tr("settings.section.llm"))
        self._lbl_llm_enabled.setText(tr("settings.llm.enabled"))
        self._lbl_llm_url.setText(tr("settings.llm.url"))
        self._lbl_llm_model.setText(tr("settings.llm.model"))
        self._lbl_llm_timeout.setText(tr("settings.llm.timeout_ms"))
        self._lbl_llm_floor.setText(tr("settings.llm.floor_score"))
        self._lbl_llm_temp.setText(tr("settings.llm.temperature"))
        self._btn_llm_test.setText(tr("settings.llm.test"))
