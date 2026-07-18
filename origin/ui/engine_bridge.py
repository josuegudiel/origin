"""Adaptador QObject que escucha el `EventBus` del engine y re-emite como Qt signals.

Construir `EngineBridge` en el thread de la UI: signals emitidas desde threads del
engine se entregan a slots del main thread vía auto-connection → QueuedConnection.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from ..engine.events import EventBus, EventType


class EngineBridge(QObject):
    engine_state = Signal(str)
    audio_level = Signal(float)
    transcription_done = Signal(dict)
    match_done = Signal(dict)
    command_executed = Signal(dict)
    profile_changed = Signal(str)
    language_changed = Signal(str)
    config_reloaded = Signal()
    config_error = Signal(str)
    log_event = Signal(dict)
    # ===== v0.3 =====
    tts_started = Signal(dict)
    tts_done = Signal(dict)
    hotas_event = Signal(dict)
    llm_intent_resolved = Signal(dict)
    script_step_executed = Signal(dict)
    # ===== head tracking =====
    head_pose = Signal(dict)
    head_track_state = Signal(dict)
    head_gesture = Signal(dict)

    def __init__(self, bus: EventBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._unsubs: list = []
        self._wire()

    def _wire(self) -> None:
        sub = self._bus.subscribe
        self._unsubs.extend([
            sub(EventType.ENGINE_STATE_CHANGED, self._on_state),
            sub(EventType.AUDIO_LEVEL, self._on_level),
            sub(EventType.TRANSCRIPTION_DONE, self._on_trans),
            sub(EventType.MATCH_DONE, self._on_match),
            sub(EventType.COMMAND_EXECUTED, self._on_exec),
            sub(EventType.PROFILE_CHANGED, self._on_profile),
            sub(EventType.LANGUAGE_CHANGED, self._on_lang),
            sub(EventType.CONFIG_RELOADED, self._on_reloaded),
            sub(EventType.CONFIG_ERROR, self._on_cfg_err),
            sub(EventType.LOG, self._on_log),
            sub(EventType.TTS_STARTED, lambda p: self.tts_started.emit(dict(p))),
            sub(EventType.TTS_DONE, lambda p: self.tts_done.emit(dict(p))),
            sub(EventType.HOTAS_BUTTON_PRESSED, lambda p: self.hotas_event.emit(dict(p))),
            sub(EventType.LLM_INTENT_RESOLVED, lambda p: self.llm_intent_resolved.emit(dict(p))),
            sub(EventType.SCRIPT_STEP_EXECUTED, lambda p: self.script_step_executed.emit(dict(p))),
            sub(EventType.HEAD_POSE, lambda p: self.head_pose.emit(dict(p))),
            sub(EventType.HEAD_TRACK_STATE, lambda p: self.head_track_state.emit(dict(p))),
            sub(EventType.HEAD_GESTURE, lambda p: self.head_gesture.emit(dict(p))),
        ])

    def teardown(self) -> None:
        for u in self._unsubs:
            try:
                u()
            except Exception:
                pass
        self._unsubs.clear()

    # ---- Forwarders (corren en thread emisor; Qt los queueá al main thread) ----

    def _on_state(self, p: dict[str, Any]) -> None:
        self.engine_state.emit(p.get("state", ""))

    def _on_level(self, p: dict[str, Any]) -> None:
        self.audio_level.emit(float(p.get("rms", 0.0)))

    def _on_trans(self, p: dict[str, Any]) -> None:
        self.transcription_done.emit(dict(p))

    def _on_match(self, p: dict[str, Any]) -> None:
        self.match_done.emit(dict(p))

    def _on_exec(self, p: dict[str, Any]) -> None:
        self.command_executed.emit(dict(p))

    def _on_profile(self, p: dict[str, Any]) -> None:
        self.profile_changed.emit(p.get("profile_id", ""))

    def _on_lang(self, p: dict[str, Any]) -> None:
        self.language_changed.emit(p.get("lang", ""))

    def _on_reloaded(self, _p: dict[str, Any]) -> None:
        self.config_reloaded.emit()

    def _on_cfg_err(self, p: dict[str, Any]) -> None:
        self.config_error.emit(p.get("error", ""))

    def _on_log(self, p: dict[str, Any]) -> None:
        self.log_event.emit(dict(p))
