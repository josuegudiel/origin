"""Bus de eventos sin Qt. El engine emite; subscriptores reciben en el thread emisor.

`EngineBridge` (UI layer) hace la conversión a Qt signals con `QueuedConnection`.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    ENGINE_STATE_CHANGED = "engine_state_changed"
    AUDIO_LEVEL = "audio_level"
    TRANSCRIPTION_DONE = "transcription_done"
    MATCH_DONE = "match_done"
    COMMAND_EXECUTED = "command_executed"
    PROFILE_CHANGED = "profile_changed"
    LANGUAGE_CHANGED = "language_changed"
    CONFIG_RELOADED = "config_reloaded"
    CONFIG_ERROR = "config_error"
    LOG = "log"
    # ===== v0.3 =====
    TTS_STARTED = "tts_started"
    TTS_DONE = "tts_done"
    HOTAS_BUTTON_PRESSED = "hotas_button_pressed"
    LLM_INTENT_RESOLVED = "llm_intent_resolved"
    SCRIPT_STEP_EXECUTED = "script_step_executed"
    # ===== head tracking (webcam) =====
    HEAD_POSE = "head_pose"
    HEAD_TRACK_STATE = "head_track_state"
    HEAD_GESTURE = "head_gesture"


Listener = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[EventType, list[Listener]] = {e: [] for e in EventType}
        self._lock = threading.RLock()

    def subscribe(self, event: EventType, listener: Listener) -> Callable[[], None]:
        with self._lock:
            self._subs[event].append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._subs[event]:
                    self._subs[event].remove(listener)

        return unsubscribe

    def emit(self, event: EventType, payload: dict[str, Any] | None = None) -> None:
        with self._lock:
            subs = list(self._subs[event])
        payload = payload or {}
        for s in subs:
            try:
                s(payload)
            except Exception:
                # Un subscriber roto no debe romper a los demás ni al engine.
                logger.exception("event_listener_failed event=%s", event.value)
