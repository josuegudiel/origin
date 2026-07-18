"""Orquestador v0.3: PTT (tecla + HOTAS) + Recorder + Transcriber + IntentMatcher
+ StepExecutor (DSL) + Piper TTS + LLM fallback (Ollama).

Estados: LOADING → READY → RECORDING → TRANSCRIBING → (RESOLVING_INTENT) →
RUNNING_SCRIPT → (SPEAKING) → READY. Transiciones protegidas por `_state_lock`.

PTT-press durante TRANSCRIBING / RESOLVING_INTENT / RUNNING_SCRIPT → `ptt_busy`.
PTT-press durante SPEAKING con `tts.cancel_on_ptt` → corta TTS, arranca RECORDING.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Any

from . import config as cfgmod
from . import keypress
from .audio import Recorder
from .events import EventBus, EventType
from .head_gestures import GestureDetector
from .headtrack import HeadPose, HeadTracker
from .hotas import HotasListener
from .llm import LLMIntentResolver, OllamaClient
from .opentrack_out import OpenTrackSender
from .paths import bundled_voices_dir, default_paths, piper_exe_path
from .profiles import ProfileRegistry
from .script import StepExecutionState, StepExecutor
from .stt import Transcriber
from .tts import PiperTTS

logger = logging.getLogger(__name__)


class State(str, Enum):
    LOADING = "loading_model"
    READY = "ready"
    PAUSED = "paused"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    EXECUTING = "executing"           # legado v0.2 (execute_command_test)
    RUNNING_SCRIPT = "running_script"
    SPEAKING = "speaking"
    RESOLVING_INTENT = "resolving_intent"
    ERROR = "error"


_MIN_RECORD_SECONDS = 0.3
_BUSY_STATES = {
    State.TRANSCRIBING,
    State.EXECUTING,
    State.RUNNING_SCRIPT,
    State.RESOLVING_INTENT,
}


def _load_tts_phrases(lang: str) -> dict[str, str]:
    """Carga `tts_phrases_{lang}.json` adyacente al módulo. Devuelve {} si falta."""
    path = Path(__file__).resolve().parent / f"tts_phrases_{lang}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("tts_phrases_load_failed lang=%s", lang)
        return {}


class Orchestrator:
    def __init__(
        self,
        config_path: Path,
        bus: EventBus,
        dry_run: bool = False,
    ) -> None:
        self._config_path = config_path
        self._bus = bus
        self._dry_run = dry_run

        cf = cfgmod.load(config_path)
        self._cf = cf
        self._profiles = ProfileRegistry(cf)
        self._settings = cf.settings

        self._recorder: Recorder | None = None
        self._transcriber: Transcriber | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._kb_listener: Any | None = None
        self._hk_listener: Any | None = None
        self._watchdog_obs: Any | None = None
        self._tts: PiperTTS | None = None
        self._hotas: HotasListener | None = None
        self._llm: LLMIntentResolver | None = None
        self._head: HeadTracker | None = None
        self._opentrack: OpenTrackSender | None = None
        self._gestures = GestureDetector()
        self._script_executor: StepExecutor | None = None
        self._script_states: dict[str, StepExecutionState] = {}
        self._script_cancel = threading.Event()

        self._tts_phrases = {"es": _load_tts_phrases("es"), "en": _load_tts_phrases("en")}

        self._state = State.LOADING
        self._state_lock = threading.RLock()
        self._ptt_pressed = False
        self._capture_started_at: float | None = None
        self._capture_profile_id: str | None = None

    # ====================================================================
    # Ciclo de vida
    # ====================================================================

    def start(self, autoload_model: bool = True) -> None:
        logger.info("orchestrator_start dry_run=%s", self._dry_run)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="origin-stt")
        self._recorder = Recorder(
            sample_rate=self._settings.sample_rate,
            mic_device=self._settings.mic_device,
            max_record_seconds=self._settings.max_record_seconds,
            on_level=self._emit_audio_level,
        )
        self._recorder.start_stream()
        self._transcriber = Transcriber(
            model_name=self._settings.whisper_model,
            device_preference=self._settings.whisper_device,
            compute_type=self._settings.whisper_compute_type,
        )
        self._build_tts()
        self._build_script_executor()
        self._build_llm_if_enabled()
        if autoload_model:
            self._executor.submit(self._load_model)
        self._start_keyboard_listeners()
        self._start_hotas_listener()
        self._start_head_tracker()
        self._start_watchdog()

    def shutdown(self) -> None:
        logger.info("orchestrator_shutdown")
        # Orden: cortar I/O externo (HOTAS, TTS, watchdog, keyboard) ANTES de
        # esperar al executor; setear cancel para abortar scripts en vuelo.
        self._script_cancel.set()
        if self._hotas:
            self._hotas.stop()
        if self._head:
            self._head.stop()
        if self._opentrack:
            self._opentrack.close()
        if self._tts:
            self._tts.shutdown()
        self._stop_watchdog()
        self._stop_keyboard_listeners()
        if self._recorder:
            self._recorder.stop_stream()
        if self._executor:
            # cancel_futures=True para que un LLM lento o un script colgado no
            # bloqueen el shutdown indefinidamente.
            self._executor.shutdown(wait=True, cancel_futures=True)

    # ====================================================================
    # Construcción de módulos
    # ====================================================================

    def _build_tts(self) -> None:
        self._tts = PiperTTS(
            piper_exe=piper_exe_path(),
            bundled_voices_dir=bundled_voices_dir(),
            user_voices_dir=default_paths().voices_dir,
            voice_es=self._settings.tts.voice_es,
            voice_en=self._settings.tts.voice_en,
            bus=self._bus,
        )

    def _build_script_executor(self) -> None:
        self._script_executor = StepExecutor(
            keypress_exec=lambda combos, delay, dry: keypress.execute(combos, delay, dry),
            keypress_exec_held=lambda combo, ms, dry: keypress.execute_held(combo, ms, dry),
            # Métodos bound a `self`: siempre re-leen self._tts / self._settings.
            tts_say=self._tts_say,
            tts_cancel=self._tts_cancel_indirect,
            set_substate=lambda s: self._set_state(State(s)),
            bus=self._bus,
            settings_provider=lambda: self._settings,
            i18n_say=self._i18n_say,
            dry_run=self._dry_run,
        )

    def _build_llm_if_enabled(self) -> None:
        if not self._settings.llm.enabled:
            self._llm = None
            return
        client = OllamaClient(
            self._settings.llm.base_url,
            self._settings.llm.model,
            self._settings.llm.timeout_ms,
        )
        self._llm = LLMIntentResolver(client, self._settings.llm)
        # Preflight no-bloqueante: si falla, banner amarillo vía CONFIG_ERROR.
        if self._executor:
            self._executor.submit(self._llm_preflight, client)

    def _llm_preflight(self, client: OllamaClient) -> None:
        err = client.preflight()
        if err:
            logger.warning("llm_preflight_failed err=%s", err)
            self._bus.emit(EventType.CONFIG_ERROR, {"error": f"LLM: {err}", "kind": "llm"})

    # ====================================================================
    # API pública
    # ====================================================================

    def pause(self) -> None:
        with self._state_lock:
            if self._state == State.PAUSED:
                return
            self._set_state(State.PAUSED)

    def resume(self) -> None:
        with self._state_lock:
            if self._state != State.PAUSED:
                return
            self._set_state(State.READY)

    def is_paused(self) -> bool:
        with self._state_lock:
            return self._state == State.PAUSED

    @property
    def state(self) -> State:
        with self._state_lock:
            return self._state

    @property
    def config(self) -> cfgmod.CommandsFileV3:
        return self._cf

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def profiles(self) -> ProfileRegistry:
        return self._profiles

    def set_active_profile(self, profile_id: str) -> bool:
        ok = self._profiles.set_active(profile_id)
        if ok:
            self._bus.emit(EventType.PROFILE_CHANGED, {"profile_id": profile_id})
        return ok

    def cycle_profile(self) -> str:
        new_id = self._profiles.cycle_next()
        self._bus.emit(EventType.PROFILE_CHANGED, {"profile_id": new_id})
        return new_id

    def set_active_language(self, lang: str) -> None:
        if lang not in ("es", "en"):
            raise ValueError(f"idioma inválido: {lang}")
        self._cf = self._cf.with_settings(active_language=lang)
        self._settings = self._cf.settings
        self._bus.emit(EventType.LANGUAGE_CHANGED, {"lang": lang})

    def set_setting(self, **changes: Any) -> None:
        """Aplica cambios al bloque settings, emite eventos y persiste a disco."""
        old = self._settings
        new_cf = self._cf.with_settings(**changes)
        try:
            cfgmod.save_atomic(new_cf, self._config_path)
        except OSError as e:
            # Disk full, permission denied, etc. — no actualizamos in-memory para
            # mantener la consistencia entre RAM y disco; avisamos a la UI.
            logger.error("set_setting_save_failed: %s", e)
            self._bus.emit(
                EventType.CONFIG_ERROR,
                {"error": f"No se pudo guardar settings: {e}"},
            )
            return
        self._cf = new_cf
        self._settings = new_cf.settings

        if "mic_device" in changes and self._recorder:
            self._recorder.restart_stream(self._settings.mic_device)
        if any(k in changes for k in ("whisper_model", "whisper_device", "whisper_compute_type")):
            self._rebuild_transcriber()
        if "ptt_key" in changes or "profile_switch_hotkey" in changes:
            self._stop_keyboard_listeners()
            self._start_keyboard_listeners()
        if "tts" in changes and self._tts:
            self._tts.update_voices(self._settings.tts.voice_es, self._settings.tts.voice_en)
        if "hotas" in changes:
            if self._hotas:
                self._hotas.stop()
                self._hotas = None
            self._start_hotas_listener()
        if "headtrack" in changes:
            # Cambios en cámara/opentrack/backend requieren reconstruir el tracker.
            self._stop_head_tracker()
            self._start_head_tracker()
        if "llm" in changes:
            self._build_llm_if_enabled()
        if "active_language" in changes and old.active_language != self._settings.active_language:
            self._bus.emit(EventType.LANGUAGE_CHANGED, {"lang": self._settings.active_language})
        if "active_profile" in changes and old.active_profile != self._settings.active_profile:
            self.set_active_profile(self._settings.active_profile)

    def reload_config(self) -> bool:
        try:
            new_cf = cfgmod.load(self._config_path)
        except cfgmod.ConfigError as e:
            logger.error("config_reload_failed: %s", e)
            self._bus.emit(EventType.CONFIG_ERROR, {"error": str(e)})
            return False
        with self._state_lock:
            self._cf = new_cf
            self._settings = new_cf.settings
            self._profiles.replace_config(new_cf)
            # Limpiar script_states de perfiles que ya no existen.
            valid_ids = {p.id for p in new_cf.profiles}
            self._script_states = {k: v for k, v in self._script_states.items() if k in valid_ids}
        self._bus.emit(EventType.CONFIG_RELOADED, {})
        return True

    def execute_command_test(self, command_id: str, profile_id: str | None = None) -> None:
        """Ejecuta los steps de un comando sin necesidad de hablar (botón Test del editor).

        Esta ruta NO pasa por el executor, así que no hay `_on_process_done` que
        resetee el state. Lo hacemos en finally — sin esto el dashboard quedaba
        atascado en RUNNING_SCRIPT tras un Test.
        """
        pid = profile_id or self._profiles.active_id
        prof = self._cf.get_profile(pid)
        cmd = next((c for c in prof.commands if c.id == command_id), None)
        if cmd is None:
            raise KeyError(command_id)
        try:
            self._dispatch_command(cmd, self._settings.active_language, test=True)
        finally:
            with self._state_lock:
                if self._state not in (State.PAUSED, State.ERROR):
                    self._set_state(State.READY)

    # ====================================================================
    # Internos
    # ====================================================================

    def _set_state(self, new_state: State) -> None:
        with self._state_lock:
            if self._state == new_state:
                return
            self._state = new_state
        self._bus.emit(EventType.ENGINE_STATE_CHANGED, {"state": new_state.value})

    def _emit_audio_level(self, rms: float) -> None:
        self._bus.emit(EventType.AUDIO_LEVEL, {"rms": rms})

    def _load_model(self) -> None:
        assert self._transcriber is not None
        try:
            self._transcriber.load()
        except Exception as e:
            logger.exception("model_load_failed")
            self._bus.emit(EventType.CONFIG_ERROR, {"error": f"Whisper load failed: {e}"})
            self._set_state(State.ERROR)
            return
        self._set_state(State.READY)

    def _rebuild_transcriber(self) -> None:
        assert self._executor is not None
        self._set_state(State.LOADING)
        self._transcriber = Transcriber(
            model_name=self._settings.whisper_model,
            device_preference=self._settings.whisper_device,
            compute_type=self._settings.whisper_compute_type,
        )
        self._executor.submit(self._load_model)

    # ----- Keyboard hooks -----

    def _start_keyboard_listeners(self) -> None:
        from pynput import keyboard as kb  # lazy

        ptt_key = self._parse_pynput_key(self._settings.ptt_key)

        def on_press(key: Any) -> None:
            if self._matches(key, ptt_key):
                self._on_ptt_press()

        def on_release(key: Any) -> None:
            if self._matches(key, ptt_key):
                self._on_ptt_release()

        self._kb_listener = kb.Listener(on_press=on_press, on_release=on_release)
        self._kb_listener.start()

        try:
            hk_spec = self._format_hotkey_for_pynput(self._settings.profile_switch_hotkey)
            self._hk_listener = kb.GlobalHotKeys({hk_spec: self._on_cycle_hotkey})
            self._hk_listener.start()
        except Exception:
            logger.exception(
                "profile_switch_hotkey_failed hotkey=%s",
                self._settings.profile_switch_hotkey,
            )

    def _stop_keyboard_listeners(self) -> None:
        for listener in (self._kb_listener, self._hk_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    logger.exception("keyboard_listener_stop_failed")
        self._kb_listener = None
        self._hk_listener = None

    @staticmethod
    def _parse_pynput_key(name: str) -> Any:
        from pynput import keyboard as kb

        n = name.lower().strip()
        n = {"esc": "escape", "return": "enter"}.get(n, n)
        if hasattr(kb.Key, n):
            return getattr(kb.Key, n)
        if len(n) == 1:
            return kb.KeyCode.from_char(n)
        raise ValueError(f"PTT key '{name}' no soportada por pynput")

    @staticmethod
    def _format_hotkey_for_pynput(combo: str) -> str:
        parts = []
        for p in combo.lower().split("+"):
            p = p.strip()
            if not p:
                continue
            if len(p) == 1 and p.isalnum():
                parts.append(p)
            else:
                parts.append(f"<{p}>")
        return "+".join(parts)

    @staticmethod
    def _matches(received: Any, expected: Any) -> bool:
        try:
            return received == expected
        except Exception:
            return False

    # ----- HOTAS -----

    def _start_hotas_listener(self) -> None:
        cfg = self._settings.hotas
        if not cfg.enabled or not cfg.button_binding:
            return
        self._hotas = HotasListener(
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
            poll_hz=cfg.poll_hz,
        )
        self._hotas.set_binding(cfg.button_binding)
        self._hotas.start()
        self._bus.emit(EventType.HOTAS_BUTTON_PRESSED, {"event": "listener_started", "binding": cfg.button_binding})

    # ----- Head tracking -----

    def _start_head_tracker(self) -> None:
        cfg = self._settings.headtrack
        if not cfg.enabled:
            return
        if cfg.opentrack.enabled:
            self._opentrack = OpenTrackSender(cfg.opentrack.host, cfg.opentrack.port)
            self._opentrack.open()
        self._gestures.reset()
        self._head = HeadTracker(cfg, self._bus, on_pose=self._on_head_pose)
        self._head.start()

    def _stop_head_tracker(self) -> None:
        if self._head:
            self._head.stop()
            self._head = None
        if self._opentrack:
            self._opentrack.close()
            self._opentrack = None

    def calibrate_head(self) -> None:
        """Marca la pose actual como el centro (llamado desde la UI)."""
        if self._head:
            self._head.calibrate()

    def _on_head_pose(self, pose: HeadPose) -> None:
        # 1) OpenTrack: reenvía la pose 6DoF para el head-look del juego.
        if self._opentrack is not None:
            self._opentrack.send(*pose.as_tuple())
        # 2) Gestos → comando (reusa el dispatch endurecido).
        gesture = self._gestures.feed(pose, time.monotonic())
        if gesture is None:
            return
        self._bus.emit(EventType.HEAD_GESTURE, {"gesture": gesture})
        # Solo actuamos si no estamos ocupados (evita pisar un PTT en curso).
        with self._state_lock:
            if self._state in _BUSY_STATES or self._state in (
                State.PAUSED, State.LOADING, State.ERROR, State.RECORDING
            ):
                return
        binding = next(
            (b for b in self._settings.headtrack.gestures
             if b.enabled and b.gesture == gesture),
            None,
        )
        if binding is None:
            return
        prof = self._profiles.active()
        cmd = next((c for c in prof.commands if c.id == binding.command_id), None)
        if cmd is not None:
            self._dispatch_command(cmd, self._settings.active_language)

    # ----- PTT flow -----

    def _on_ptt_press(self) -> None:
        with self._state_lock:
            if self._state in (State.PAUSED, State.LOADING, State.ERROR):
                logger.debug("ptt_press_ignored state=%s", self._state.value)
                return
            # SPEAKING + cancel_on_ptt → cortar TTS y proceder a grabar.
            # No emitimos READY intermedio: la transición visible es SPEAKING → RECORDING.
            if self._state == State.SPEAKING and self._settings.tts.cancel_on_ptt:
                if self._tts:
                    self._tts.cancel()
            elif self._state in _BUSY_STATES:
                logger.info("ptt_busy state=%s", self._state.value)
                return
            if self._ptt_pressed:
                return
            self._ptt_pressed = True
            self._capture_started_at = time.monotonic()
            self._capture_profile_id = self._profiles.active_id
            assert self._recorder is not None
            self._recorder.begin_capture()
            self._set_state(State.RECORDING)

    def _on_ptt_release(self) -> None:
        with self._state_lock:
            if not self._ptt_pressed:
                return
            self._ptt_pressed = False
            if self._state != State.RECORDING:
                return
            assert self._recorder is not None
            audio = self._recorder.end_capture()
            elapsed = (
                time.monotonic() - self._capture_started_at
                if self._capture_started_at else 0.0
            )
            if elapsed < _MIN_RECORD_SECONDS or audio.size == 0:
                logger.info("ptt_too_short elapsed=%.2fs", elapsed)
                self._set_state(State.READY)
                return
            self._set_state(State.TRANSCRIBING)
        assert self._executor is not None
        profile_id = self._capture_profile_id or self._profiles.active_id
        fut = self._executor.submit(self._process_audio, audio, profile_id)
        fut.add_done_callback(self._on_process_done)

    def _process_audio(self, audio: Any, profile_id: str) -> dict[str, Any]:
        t0 = time.monotonic()
        lang = self._settings.active_language
        text = ""
        try:
            assert self._transcriber is not None
            text = self._transcriber.transcribe(audio, lang)
        except Exception as e:
            logger.exception("transcription_failed")
            return {"error": str(e)}
        stt_ms = int((time.monotonic() - t0) * 1000)
        self._bus.emit(
            EventType.TRANSCRIPTION_DONE,
            {"text": text, "language": lang, "elapsed_ms": stt_ms},
        )

        try:
            prof = self._cf.get_profile(profile_id)
        except KeyError:
            prof = self._profiles.active()
        from .intent import IntentMatcher

        matcher = (
            self._profiles.matcher()
            if prof.id == self._profiles.active_id
            else IntentMatcher(prof.commands)
        )
        t1 = time.monotonic()
        threshold = self._settings.fuzz_threshold
        result = matcher.match(text, lang, threshold)
        match_ms = int((time.monotonic() - t1) * 1000)
        self._bus.emit(
            EventType.MATCH_DONE,
            {
                "text": text,
                "command_id": result.command.id if result.command else None,
                "score": float(result.score),
                "phrase": result.phrase,
                "keys": list(result.command.keys) if result.command else None,
                "elapsed_ms": match_ms,
            },
        )

        if result.command is not None:
            self._dispatch_command(result.command, lang)
            return {"ok": True, "matched": True}

        # ----- LLM fallback -----
        llm_cfg = self._settings.llm
        if (
            self._llm is not None
            and llm_cfg.enabled
            and text.strip()
            and llm_cfg.floor_score <= result.score < threshold
        ):
            self._set_state(State.RESOLVING_INTENT)
            resolution = self._llm.resolve(text, prof, lang)
            self._bus.emit(
                EventType.LLM_INTENT_RESOLVED,
                {
                    "transcription": text,
                    "command_ids": list(resolution.commands),
                    "confidence": resolution.confidence,
                    "reasoning": resolution.reasoning,
                },
            )
            if resolution.confidence != "low" and resolution.commands:
                for cmd_id in resolution.commands:
                    cmd = next((c for c in prof.commands if c.id == cmd_id), None)
                    if cmd is not None:
                        self._dispatch_command(cmd, lang)

        return {"ok": True, "matched": False}

    def _dispatch_command(
        self,
        cmd: cfgmod.Command,
        lang: str,
        *,
        test: bool = False,
    ) -> None:
        """Ejecuta un comando vía StepExecutor (unifica keys+steps)."""
        assert self._script_executor is not None
        steps = cfgmod.command_as_steps(cmd, self._settings)
        # `setdefault` bajo lock — reload_config puede mutar `_script_states`.
        with self._state_lock:
            state = self._script_states.setdefault(
                self._profiles.active_id, StepExecutionState()
            )
        # Clear (no reasignar) — un shutdown() en flight que llamó .set() sobre el
        # mismo Event mantiene su efecto, no se pierde por re-asignación.
        self._script_cancel.clear()
        self._set_state(State.RUNNING_SCRIPT)
        try:
            self._script_executor.execute(steps, state, lang, cancel=self._script_cancel)
        finally:
            self._bus.emit(
                EventType.COMMAND_EXECUTED,
                {
                    "command_id": cmd.id,
                    "keys": list(cmd.keys),
                    "steps_count": len(steps),
                    "dry_run": self._dry_run,
                    "test": test,
                },
            )

    def _on_process_done(self, fut: Future[dict[str, Any]]) -> None:
        try:
            fut.result()
        except Exception:
            logger.exception("process_audio_failed")
        finally:
            with self._state_lock:
                if self._state not in (State.PAUSED, State.ERROR):
                    self._set_state(State.READY)

    def _on_cycle_hotkey(self) -> None:
        try:
            self.cycle_profile()
        except Exception:
            logger.exception("cycle_profile_failed")

    # ----- TTS helpers -----

    def _tts_say(self, text: str, lang: str) -> None:
        # Gate por settings.tts.enabled — el toggle desde Settings tiene que
        # cortar TODO TTS, incluyendo say steps explícitos en scripts.
        if not self._tts or not self._settings.tts.enabled:
            return
        self._tts.say(
            text,
            lang,
            speed=self._settings.tts.speed,
            volume=self._settings.tts.volume,
        )

    def _tts_cancel_indirect(self) -> None:
        # Indirección para evitar capturar `self._tts.cancel` con bind temprano:
        # si TTS se rebuildea, el lookup en runtime sigue válido.
        if self._tts:
            self._tts.cancel()

    def _i18n_say(self, key: str, lang: str) -> str:
        return self._tts_phrases.get(lang, {}).get(key) or f"[missing:{key}]"

    # ----- Watchdog (hot-reload del commands.yaml) -----

    def _start_watchdog(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler  # type: ignore[import-untyped]
            from watchdog.observers import Observer  # type: ignore[import-untyped]
        except ImportError:
            logger.info("watchdog_unavailable hot_reload_disabled")
            return

        debounce_seconds = 0.3
        last_fired = [0.0]
        target = str(self._config_path.resolve())
        path_dir = str(self._config_path.parent.resolve())

        outer = self

        class Handler(FileSystemEventHandler):
            def on_modified(self, event: Any) -> None:
                if event.is_directory:
                    return
                try:
                    if Path(event.src_path).resolve().as_posix() != Path(target).as_posix():
                        return
                except Exception:
                    return
                now = time.monotonic()
                if now - last_fired[0] < debounce_seconds:
                    return
                last_fired[0] = now
                threading.Timer(debounce_seconds, outer.reload_config).start()

        obs = Observer()
        obs.schedule(Handler(), path_dir, recursive=False)
        obs.daemon = True
        obs.start()
        self._watchdog_obs = obs

    def _stop_watchdog(self) -> None:
        if self._watchdog_obs is None:
            return
        try:
            self._watchdog_obs.stop()
            self._watchdog_obs.join(timeout=2)
        except Exception:
            logger.exception("watchdog_stop_failed")
        finally:
            self._watchdog_obs = None
