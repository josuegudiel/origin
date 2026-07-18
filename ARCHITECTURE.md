# Origin v0.3 — Architecture

## 1. Overview

Origin es un asistente de voz bilingüe (ES/EN) push-to-talk para Star Citizen 4.x. Captura audio mientras se mantiene una tecla (default `F12`) o un botón de HOTAS, transcribe con `faster-whisper` (modelo `small` por default, bundled en el instalador), matchea la transcripción contra el catálogo de frases del perfil activo con `rapidfuzz.token_set_ratio`, y si el score supera `fuzz_threshold` ejecuta los `keys` o `steps` del comando vía `pydirectinput` (DirectInput, no SendInput — Star Citizen ignora SendInput). El motor opcionalmente sintetiza un acknowledge con Piper TTS local, y si ningún comando matchea pero la transcripción no está vacía puede pedirle a un LLM local (Ollama) que resuelva la intención contra el catálogo del perfil.

Decisiones top-level: (a) **engine sin Qt** — `origin/engine/*` no importa PySide6, lo que hace los tests headless en Linux/CI y desacopla la lógica del runtime de la GUI; el puente es un `EventBus` propio (`engine/events.py`) que la UI envuelve en `EngineBridge` (Qt signals con `QueuedConnection`). (b) **PTT siempre, nunca hot-word**: cero falsos positivos, latencia predecible. (c) **Bilingüe con toggle en runtime** — el idioma activo `es|en` lo elige el usuario antes de hablar (botones del header), filtra phrases del matcher y selecciona voz de TTS. (d) **Perfiles** intercambiables (flight, on-foot, mining...) con hotkey global `Ctrl+F12` para ciclar sin abrir la UI. (e) **DSL de scripting** opcional por comando (`steps:`), con `key`/`wait`/`say`/`say_key`/`set`/`if`/`goto`/`label`/`repeat`. (f) **LLM fallback** entre `floor_score` y `fuzz_threshold` — único path que cuesta latencia variable. (g) Distribución como **instalador Windows onedir** (PyInstaller + Inno Setup) con Piper, voces y modelo Whisper pre-empaquetados.

## 2. Capas y threading

```
   +---------------------------------------------------------------------------+
   |                       Process (single instance via QLockFile)              |
   +---------------------------------------------------------------------------+

                          +------------------------------------+
                          |   Main / Qt event loop (UI thread) |
                          |   - QApplication, MainWindow       |
                          |   - Pages: dashboard, commands,    |
                          |     profiles, settings, logs       |
                          |   - OriginTray (QSystemTrayIcon)   |
                          |   - EngineBridge (QObject)         |
                          +------------------+-----------------+
                                             ^
                                             | Qt signals (auto-connection
                                             | → QueuedConnection cuando
                                             |   se emiten desde otros threads)
                                             |
   +-----------------------------------------+-----------------------------------------+
   |                              EventBus  (engine/events.py)                          |
   |   subscribe / emit, fan-out síncrono en el thread del emisor                       |
   +-----------------------------------------------------------------------------------+
       ^         ^         ^         ^        ^                ^             ^
       |         |         |         |        |                |             |
   +---+--+  +---+---+ +---+---+ +---+----+ +-+------+   +-----+------+ +----+----+
   | kb   |  | hotkey| | sound | | hotas  | | piper  |   | watchdog   | | STT     |
   | ptt  |  | global| | dev cb| | device | | stdout | | observer    | | worker  |
   | hook |  | hotkey| |       | | loop   | | reader |   |            | | thread  |
   |daemon|  |daemon | |       | | (1×gp) | | (main) |   | daemon     | | (1×)    |
   +------+  +-------+ +-------+ +--------+ +--------+   +------------+ +---------+
     pynput   pynput   PortAudio  inputs    subprocess     watchdog       Future
     Listener Global   InputStream                                        callback
              HotKeys                                                     -> bus

                           +-----------------------------+
                           |   Subsistemas del engine    |
                           |  - Recorder (audio.py)      |
                           |  - Transcriber (stt.py)     |
                           |  - IntentMatcher (intent.py)|
                           |  - StepExecutor (script.py) |
                           |  - PiperTTS (tts.py)        |
                           |  - HotasListener (hotas.py) |
                           |  - LLMIntentResolver (llm.py)|
                           |  - ProfileRegistry          |
                           |  - keypress.execute (DirectInput)|
                           +-----------------------------+
                                  ↑ orquestados por
                           Orchestrator (runtime.py)
```

Reglas de oro:
- Cualquier hilo del engine puede llamar `bus.emit()`. Cada subscriber corre en ese hilo emisor; los subscribers Qt re-emiten signals que llegan al main thread vía auto-connection (`QueuedConnection` porque `bridge` se crea en el main thread).
- El `Orchestrator` protege transiciones de estado y mutaciones de `_script_states` con `self._state_lock` (`RLock` para soportar re-entradas como `_dispatch_command` invocando `_set_state` desde dentro del bloque).
- El recorder mantiene el `sounddevice.InputStream` siempre abierto; `begin_capture()` y `end_capture()` arman/cierran ventanas dentro del stream continuo. El callback de PortAudio es real-time (latencia ms), así que solo hace `np.copy` + push al buffer y calcula RMS para el VU meter — sin I/O, sin locks largos.
- El engine **no importa Qt en ningún lado**: `grep -r "PySide6" origin/engine/` da cero matches. Esto se preserva como invariante arquitectónico.
- La UI puede vivir sin engine para tests con un `EventBus` falso, y el engine puede correr sin UI (`origin --headless`).

## 3. State machine del orchestrator

Enum `State` definido en `origin/engine/runtime.py:36`. Visible para la UI vía `EventType.ENGINE_STATE_CHANGED`.

| Estado              | Significado                                                                 |
|---------------------|----------------------------------------------------------------------------|
| `LOADING`           | Cargando modelo Whisper (warm-up con 1s de silencio sintético).            |
| `READY`             | Esperando PTT.                                                              |
| `PAUSED`            | Usuario pausó (header / tray). Ignora todo PTT.                             |
| `RECORDING`         | PTT down; sounddevice está acumulando audio en buffer.                      |
| `TRANSCRIBING`      | `faster-whisper` corriendo en el worker `origin-stt`.                       |
| `EXECUTING`         | Legado v0.2 (`execute_command_test` antiguo). v0.3 lo cubre `RUNNING_SCRIPT`. |
| `RUNNING_SCRIPT`    | `StepExecutor.execute()` está iterando los steps del comando matcheado.     |
| `SPEAKING`          | Subproceso `piper.exe` activo y `sounddevice.RawOutputStream` reproduciendo.|
| `RESOLVING_INTENT`  | LLM fallback en vuelo (`OllamaClient.chat_json`).                           |
| `ERROR`             | Whisper falló al cargar. Banner rojo en la UI; PTT ignorado.                |

`_BUSY_STATES = {TRANSCRIBING, EXECUTING, RUNNING_SCRIPT, RESOLVING_INTENT}` (`runtime.py:50`). PTT en estos estados emite `ptt_busy` en logs y retorna. `SPEAKING` no es busy: si `settings.tts.cancel_on_ptt` está en `True` (default), el PTT corta el TTS con `PiperTTS.cancel()` y entra a `RECORDING`. `PAUSED`/`LOADING`/`ERROR` también ignoran PTT.

Transiciones legales (origen → destino):

| De \ A              | LOADING | READY | PAUSED | RECORDING | TRANSCRIBING | RUNNING_SCRIPT | SPEAKING | RESOLVING_INTENT | ERROR |
|---------------------|:-------:|:-----:|:------:|:---------:|:------------:|:--------------:|:--------:|:----------------:|:-----:|
| LOADING             |         |   *   |        |           |              |                |          |                  |   *   |
| READY               |    *    |       |   *    |     *     |              |                |          |                  |       |
| PAUSED              |         |   *   |        |           |              |                |          |                  |       |
| RECORDING           |         |   *   |        |           |       *      |                |          |                  |       |
| TRANSCRIBING        |         |   *   |        |           |              |       *        |          |        *         |       |
| RUNNING_SCRIPT      |         |   *   |        |           |              |                |    *     |                  |       |
| SPEAKING            |         |   *   |        |     *     |              |       *        |          |                  |       |
| RESOLVING_INTENT    |         |   *   |        |           |              |       *        |          |                  |       |
| ERROR               |         |       |        |           |              |                |          |                  |       |

`_set_state` es no-op si el nuevo estado coincide con el actual; solo emite `ENGINE_STATE_CHANGED` en cambios reales (`runtime.py:335`).

## 4. Threading model detallado

| Thread | Qué hace | Quién lo crea | Cuándo termina |
|---|---|---|---|
| Main / UI | Qt event loop (`app.exec()`). Pinta widgets, recibe signals queued. | `run_app` en `ui/app.py` | `app.quit()` desde tray. |
| `origin-stt` worker | `ThreadPoolExecutor(max_workers=1)`. Ejecuta `_load_model`, `_process_audio` y `_dispatch_command`. Single-worker para serializar contra el modelo de Whisper (no thread-safe entre `transcribe()` concurrentes — `stt.py:46`). | `Orchestrator.start()` (`runtime.py:113`) | `Orchestrator.shutdown()` con `cancel_futures=True`. |
| `pynput.keyboard.Listener` daemon | Hook global low-level del PTT key. Llama `_on_ptt_press`/`_on_ptt_release` en su propio thread daemon. | `_start_keyboard_listeners` (`runtime.py:368`) | `listener.stop()` o muerte del proceso. |
| `pynput.keyboard.GlobalHotKeys` daemon | Hook global del hotkey de ciclo de perfil (default `ctrl+f12`). Llama `cycle_profile`. | mismo método | igual. |
| PortAudio callback | Thread interno de `sounddevice`. Por cada bloque de ~30ms calcula RMS y, si `_capturing`, copia a `_buffer`. NO toca el bus directamente — emite via callback `on_level`. | `Recorder.start_stream()` (`audio.py:64`) | `stop_stream()`. |
| watchdog `Observer` daemon | Mira `commands.yaml` en disco; en `on_modified` programa `reload_config` con debounce de 300ms via `threading.Timer`. | `_start_watchdog` (`runtime.py:646`) | `Observer.stop()`+`join(2s)`. |
| HOTAS `hotas-<idx>` thread (1 por gamepad) | Bloquea en `gp.read()`; forwarda press/release del botón bindeado a callbacks. Si el device desaparece duerme 5s y reintenta. | `HotasListener.start()` (`hotas.py:80`). Daemon. | `stop()` setea `_stop` event, pero `gp.read()` puede seguir bloqueado — los threads son daemon, mueren con el proceso (ver Limitaciones). |
| `piper.exe` subprocess | Spawned por cada `say()`. Lee texto por stdin, escribe PCM int16 22050Hz mono por stdout. Stderr ignorado. | `PiperTTS.say()` (`tts.py:79`). NO es un thread Python: subproceso del SO. | `proc.wait(timeout=0.5)` o `terminate()` en cancel/shutdown. |
| Subscriber callbacks del bus | Corren sincrónicamente en el thread del emisor. UI subscribers re-emiten Qt signals (cross-thread → `QueuedConnection`). | `EventBus.subscribe()` | desubscripción / shutdown. |

## 4.1 Ciclo de vida del Orchestrator

`Orchestrator.__init__` (`runtime.py:71`) carga config y arma los subsistemas pero NO los arranca. `start()` (`runtime.py:111`) hace en orden:

1. Crea `ThreadPoolExecutor(max_workers=1, thread_name_prefix="origin-stt")`.
2. `Recorder(...).start_stream()` — abre el `InputStream` de sounddevice.
3. `Transcriber(...)` — instancia (no carga modelo aún).
4. `_build_tts()` — instancia `PiperTTS` (resuelve paths de piper.exe y voces).
5. `_build_script_executor()` — instancia `StepExecutor` con callbacks bound.
6. `_build_llm_if_enabled()` — si `settings.llm.enabled`, crea `OllamaClient` + `LLMIntentResolver` y submitea `_llm_preflight` al executor.
7. Si `autoload_model=True` (default), submitea `_load_model` al executor (corre warm-up de Whisper en background).
8. `_start_keyboard_listeners()` — pynput.Listener + GlobalHotKeys.
9. `_start_hotas_listener()` — si `settings.hotas.enabled` y hay `button_binding`.
10. `_start_watchdog()` — si `watchdog` está instalado.

`shutdown()` (`runtime.py:135`) hace el inverso, pero **el orden importa** y está explícito en el código:

1. `_script_cancel.set()` — aborta scripts en vuelo.
2. `self._hotas.stop()` — antes que nada para cortar input externo.
3. `self._tts.shutdown()` — cancel + terminate del subprocess.
4. `self._stop_watchdog()` — `.stop()` + `.join(2s)`.
5. `self._stop_keyboard_listeners()` — pynput.
6. `self._recorder.stop_stream()` — cierra PortAudio.
7. `self._executor.shutdown(wait=True, cancel_futures=True)` — clave: `cancel_futures=True` para que un LLM lento o un script colgado no bloqueen el shutdown indefinidamente.

Si `shutdown()` se llama dos veces, las operaciones son idempotentes (chequean si el recurso ya está liberado).

## 5. EventBus contract

Definido en `origin/engine/events.py`. 15 tipos de eventos enumerados en `EventType`. Pattern: emisor llama `bus.emit(event, payload_dict)`, suscriptores reciben el `dict` plano. Sin lock por subscriber — un subscriber colgado bloquea al emisor.

| Evento | Emitter | Payload | Consumer típico |
|---|---|---|---|
| `ENGINE_STATE_CHANGED` | `Orchestrator._set_state` | `{state: str}` | Dashboard, tray icon, header dot. |
| `AUDIO_LEVEL` | `Recorder` callback | `{rms: float}` | `VuMeter` widget. |
| `TRANSCRIPTION_DONE` | `_process_audio` | `{text, language, elapsed_ms}` | `TranscriptionLog`. |
| `MATCH_DONE` | `_process_audio` tras `IntentMatcher.match` | `{text, command_id, score, phrase, keys, elapsed_ms}` | Dashboard, log. |
| `COMMAND_EXECUTED` | `_dispatch_command` finally | `{command_id, keys, steps_count, dry_run, test}` | Dashboard last-exec. |
| `PROFILE_CHANGED` | `set_active_profile` / `cycle_profile` | `{profile_id}` | Header combo, tray menu. |
| `LANGUAGE_CHANGED` | `set_active_language` | `{lang}` | Header lang buttons. |
| `CONFIG_RELOADED` | `reload_config` ok | `{}` | Editor refresh, banner info. |
| `CONFIG_ERROR` | LLM preflight, save fail, reload fail | `{error, kind?}` | Banner rojo. |
| `LOG` | (reservado; sin emisores actualmente) | `{...}` | LogsViewer. |
| `TTS_STARTED` | `PiperTTS.say` | `{text, lang}` | Dashboard. |
| `TTS_DONE` | `PiperTTS.say` finally | `{text, cancelled?, error?, voice?}` | Dashboard. |
| `HOTAS_BUTTON_PRESSED` | `_start_hotas_listener` (init) | `{event, binding}` | Settings capture UI. |
| `LLM_INTENT_RESOLVED` | `_process_audio` post-LLM | `{transcription, command_ids, confidence, reasoning}` | Dashboard. |
| `SCRIPT_STEP_EXECUTED` | `StepExecutor._run_block` | `{type, pc}` | Debugging / tests. |

## 6. Schema `commands.yaml` v3

Modelo Pydantic v2 frozen en `origin/engine/config.py`. Root `CommandsFileV3` con campos `version`, `settings`, `profiles`. Acepta `version: 2` o `3` (v2 carga con defaults nuevos para `tts`/`hotas`/`llm`).

```yaml
version: 3
settings:
  ptt_key: f12
  profile_switch_hotkey: ctrl+f12
  ui_language: es                 # idioma de la GUI (es|en)
  active_profile: flight
  active_language: es             # idioma para STT + matcher + TTS (cambiable runtime)
  whisper_model: small            # tiny|base|small|medium|large-v3
  whisper_device: auto            # auto|cpu|cuda
  whisper_compute_type: auto      # auto|int8|int8_float16|float16|float32
  fuzz_threshold: 75              # 0..100; mínimo score para auto-dispatch
  mic_device: null                # int|null (default device)
  sample_rate: 16000
  max_record_seconds: 8
  inter_key_delay_ms: 30
  log_format: pretty              # pretty|json
  start_minimized: false
  autostart_windows: false
  theme: system                   # system|light|dark
  tts:
    enabled: true
    voice_es: "es_ES-mls_10246-low"
    voice_en: "en_US-amy-low"
    default_response_when_no_say: true   # si no hay say_*, usa label como ack
    cancel_on_ptt: true                  # PTT durante SPEAKING corta TTS y graba
    speed: 1.0                           # 0.5..2.0  (length_scale = 1/speed)
    volume: 1.0                          # 0.0..1.5  (gain lineal sobre PCM)
  hotas:
    enabled: false
    button_binding: null                 # "<device_idx>:<button_code>"
    poll_hz: 60                          # 10..240
  llm:
    enabled: false
    base_url: "http://localhost:11434"
    model: "llama3.1:8b"
    timeout_ms: 8000                     # 500..60000
    floor_score: 60                      # 0..100; LLM solo si floor ≤ score < threshold
    temperature: 0.2
    max_commands_per_resolution: 5
profiles:
  - id: flight
    label_es: "Vuelo"
    label_en: "Flight"
    description_es: "..."
    commands:
      - id: request_landing
        phrases_es: ["pide hangar", "solicita aterrizaje"]
        phrases_en: ["request landing"]
        keys: ["alt+n"]
        say_es: "permiso de aterrizaje solicitado"
        say_en: "landing requested"
```

Validaciones (Pydantic + custom validators):
- `id` (comando + perfil): regex `^[a-z][a-z0-9_]{0,31}$`.
- `phrases_es` o `phrases_en`: al menos una no vacía.
- `keys` o `steps`: al menos uno definido.
- `keys[i]`: regex `^[a-z0-9_+]+$` (validación real de tecla vía `keypress.parse_combo`).
- `cond` en `if`: regex `^var (op) rhs$` con `op ∈ {==, !=, >, <, >=, <=}`.
- `MAX_STEPS_PER_COMMAND = 100` (`config.py:29`) — `_count_steps` expande `repeat × times` y suma sub-bloques de `if/then/else`. Si excede, `ValidationError` en load.
- `settings.active_profile` debe existir en `profiles`.
- `extra="forbid"` en todos los modelos — typos en YAML fallan loud.

Persistencia: `save_atomic` (`config.py:497`) escribe a `tempfile.mkstemp` y hace `os.replace` → no se corrompe si el proceso muere a mitad. `to_dump` usa `by_alias=True` para que `IfStep.else_` se serialice como `else:` (consistente con YAML escrito a mano).

Migración (`config.py:382`):
- **v1 → v3**: `_migrate_v1_to_v3` colapsa `commands:` flat en un perfil `default`, renombra `language` → `active_language`, defaultea `ui_language`/`profile_switch_hotkey`. Backup `commands.v1.backup.yaml` al lado.
- **v2 → v3**: el schema v3 acepta `version: 2` literal; defaults de `tts`/`hotas`/`llm` se inyectan via `default_factory`. Pre-flight backup `commands.v2.backup.yaml` siempre.

## 7. Step types del DSL

Discriminator `type:` (Pydantic `Annotated[Union, Field(discriminator="type")]`). Sub-steps recursivos en `if.then`/`if.else`/`repeat.steps`.

| `type`     | Params                                            | Semántica |
|------------|---------------------------------------------------|-----------|
| `key`      | `combo: str`, `hold_ms: int? (0..10000)`          | Envía combo vía `pydirectinput.press`. Si `hold_ms`, usa `execute_held`. |
| `wait`     | `ms: int (0..30000)`                              | `cancel.wait(ms/1000)` — cancelable. |
| `say`      | `text? | text_es? | text_en?` (al menos uno)      | Resuelve por idioma activo (fallback al otro), llama `tts_say`. Sub-state SPEAKING. |
| `say_key`  | `key: str`                                        | Busca `key` en `tts_phrases_{lang}.json`. `[missing:key]` si no existe. |
| `set`      | `var: str (VAR_RE)`, `value: str`                 | Setea `state.vars[var] = value`. Per-profile, persiste entre invocaciones. |
| `if`       | `cond: str`, `then: list[Step]`, `else: list[Step]?` | `eval_cond` sin Python eval — solo `var op rhs`. Numérico si ambos parseables. |
| `goto`     | `label: str`                                      | Salta a `LabelStep` con `name == label` en el mismo bloque. Sin label → log warning, sigue. |
| `label`    | `name: str`                                       | No-op en ejecución; indexado en `_index_labels`. |
| `repeat`   | `times: int (1..20)`, `steps: list[Step]`         | Re-corre el inner block `times` veces; cancela en cada vuelta. |

Ejecutor en `engine/script.py:77`. Reglas anti-runaway:
- Contador `_steps_run` global por `execute()`. Si llega a `MAX_STEPS_PER_COMMAND` (100), aborta con log warning. Cubre loops infinitos por `goto`.
- `cancel: threading.Event` chequeado en cada iteración y dentro de `wait`. Shutdown setea `_script_cancel` antes de cualquier otra cosa (`runtime.py:139`).
- `vars` per-profile sobreviven entre comandos del mismo perfil; se limpian al borrarse el perfil (`reload_config`).

Ejemplo `steps:` mixto:

```yaml
- id: scan_and_engage
  phrases_es: ["escanea y ataca"]
  steps:
    - {type: key, combo: tab}
    - {type: wait, ms: 500}
    - {type: set, var: target_count, value: "1"}
    - type: if
      cond: "target_count > 0"
      then:
        - {type: say_key, key: tts.target_locked}
        - {type: repeat, times: 3, steps: [{type: key, combo: space}, {type: wait, ms: 120}]}
      else:
        - {type: say, text_es: "sin objetivo", text_en: "no target"}
```

## 8. Flujo PTT end-to-end

Caso: `phrases_es: ["pide hangar"]`, `keys: ["alt+n"]`, `say_es: "permiso solicitado"`.

| # | Acción | Thread | Notas |
|---|---|---|---|
| 1 | Usuario presiona `F12` | OS keyboard hook | `pynput.Listener` daemon detecta el press. |
| 2 | `_on_ptt_press` (`runtime.py:453`) | pynput thread | Bajo `_state_lock`: si `BUSY/PAUSED/LOADING/ERROR` → return; si `SPEAKING` + `cancel_on_ptt` → `PiperTTS.cancel()` y entra a `RECORDING`. Setea `_ptt_pressed`, `_capture_started_at = monotonic()`, `_capture_profile_id = active_id`. |
| 3 | `Recorder.begin_capture()` | pynput thread | Resetea `_buffer = []`, setea `_capturing = True` bajo lock. |
| 4 | `_set_state(RECORDING)` → emit `ENGINE_STATE_CHANGED` | pynput thread | Tray icon cambia a amarillo, header dot updates via QueuedConnection. |
| 5 | Audio fluye | PortAudio callback | Cada ~30ms el callback recibe un bloque, calcula RMS, emite `AUDIO_LEVEL`, y si `_capturing` hace `np.copy` al buffer. |
| 6 | Usuario suelta `F12` | OS keyboard hook | |
| 7 | `_on_ptt_release` (`runtime.py:475`) | pynput thread | `Recorder.end_capture()` → `np.ndarray`. Si `elapsed < 0.3s` → `READY` y return. Si OK: `state = TRANSCRIBING`. |
| 8 | `executor.submit(_process_audio, audio, profile_id)` | pynput thread | Pasa el `profile_id` capturado en paso 2 — si el usuario cambia perfil mientras transcribe, se respeta el perfil del momento de hablar. |
| 9 | `Transcriber.transcribe(audio, "es")` | `origin-stt` worker | `faster-whisper` con `beam_size=5`, `vad_filter=True`, `vad_parameters={"min_silence_duration_ms": 300}`. CUDA OOM → catch + `_downgrade_to_cpu()`. |
| 10 | emit `TRANSCRIPTION_DONE {text, language, elapsed_ms}` | worker | Dashboard agrega entrada al `TranscriptionLog`. |
| 11 | `IntentMatcher.match(text, "es", 75)` | worker | `normalize` (NFKD + lower + drop punct) + `fuzz.token_set_ratio`. Best score: 95 (matcheó "pide hangar"). |
| 12 | emit `MATCH_DONE {text, command_id, score, phrase, keys, elapsed_ms}` | worker | |
| 13 | `_dispatch_command(cmd, "es")` (`runtime.py:572`) | worker | `command_as_steps` traduce `keys: ["alt+n"]` + `say_es:"..."` a `[KeyStep("alt+n"), SayStep(text_es="permiso solicitado")]`. `_script_cancel.clear()`. `state = RUNNING_SCRIPT`. |
| 14 | `StepExecutor.execute([KeyStep, SayStep], state, "es", cancel=_script_cancel)` | worker | |
| 15 | `KeyStep("alt+n")` → `keypress.execute(["alt+n"], 30, False)` | worker | `parse_combo` → `(["alt"], "n")`. `pdi.keyDown("alt")` → `pdi.press("n")` → `pdi.keyUp("alt")`. Star Citizen recibe DirectInput. |
| 16 | emit `SCRIPT_STEP_EXECUTED {type:"key", pc:0}` | worker | |
| 17 | `SayStep` → `_say` → `set_substate("speaking")` → `tts_say("permiso solicitado", "es")` | worker | `state = SPEAKING`. |
| 18 | `PiperTTS.say` | worker (bloqueante) | Spawn `subprocess.Popen([piper.exe, --model, voice.onnx, --output-raw, --length_scale, "1.000"])`. Escribe texto a stdin, close. |
| 19 | `_play_stream(stdout)` | worker | Loop: chequea `_cancel`, `stdout.read(4096)`, aplica gain si `volume != 1.0`, `stream.write(chunk)`. Hasta EOF o cancel. |
| 20 | emit `TTS_DONE {text, cancelled}` | worker | Sub-state vuelve a `running_script`. |
| 21 | StepExecutor termina | worker | |
| 22 | `_dispatch_command` finally: emit `COMMAND_EXECUTED` | worker | |
| 23 | `_on_process_done` callback del Future | worker (callback) | Bajo `_state_lock`, si no es `PAUSED/ERROR` → `state = READY`. |
| 24 | Dashboard/tray actualizan al ver `ENGINE_STATE_CHANGED` | main UI | Vía QueuedConnection. |

Tiempos típicos (Whisper small, CPU int8):
- Paso 9 (STT): 250-600 ms (depende de longitud del audio).
- Paso 11 (match): < 5 ms para perfiles de hasta ~100 comandos × ~5 phrases.
- Paso 15 (keypress): < 10 ms.
- Paso 18-20 (TTS): ~300 ms spawn + duración del audio sintetizado.
- **Total ear-to-action**: típico 350-700 ms entre soltar PTT y que Star Citizen reciba la tecla.

Si paso 11 no matchea (`result.command is None`), saltamos al §9 (LLM fallback) antes de seguir con dispatch.

## 9. LLM fallback

Trigger (`runtime.py:546`):

```python
if (self._llm is not None
    and llm_cfg.enabled
    and text.strip()
    and llm_cfg.floor_score <= result.score < threshold):
    self._set_state(State.RESOLVING_INTENT)
    resolution = self._llm.resolve(text, prof, lang)
```

Window: el mejor score quedó por debajo de `fuzz_threshold` (no es match) pero por encima de `floor_score` (la transcripción se "parece" a algo). Defaults: `floor=60`, `threshold=75`. Score < 60 → ignoramos (probable ruido/non-command). Score ≥ 75 → ya disparamos.

Prompt schema (`llm.py:118`): system message con catálogo del perfil activo en formato `- <id> — <label> — "<frase>", "<frase>"...` (hasta 3 frases por comando). User message es la transcripción cruda. Respuesta JSON forzada con `format: "json"` de Ollama:

```json
{ "commands": ["target_crusader", "engage_quantum"],
  "confidence": "high" | "medium" | "low",
  "reasoning": "<one short sentence>" }
```

Validación post-respuesta: `IntentResolution.model_validate` + filtro de IDs (solo los que existen en el catálogo) + corte a `max_commands_per_resolution`. Si `confidence != "low"` y `commands` no está vacío, se ejecutan en orden vía `_dispatch_command`. Emite `LLM_INTENT_RESOLVED` siempre (también `low`/empty para visibilidad en el dashboard).

Preflight no-bloqueante al startup (`_llm_preflight`): `GET /api/tags`, verifica que el modelo esté pulled. Falla → banner amarillo via `CONFIG_ERROR` con `kind: "llm"`. Nunca rompe el startup del engine.

## 10. Persistence model

| Path | Contenido | Quién escribe |
|---|---|---|
| `%APPDATA%/Origin/commands.yaml` | Perfiles + settings (editable a mano). | App vía `save_atomic`; usuario vía editor externo. |
| `%APPDATA%/Origin/commands.v1.backup.yaml` | Backup pre-migración v1. | `_save_backup` (idempotente). |
| `%APPDATA%/Origin/commands.v2.backup.yaml` | Backup pre-load de v2. | idem. |
| `%APPDATA%/Origin/voices/*.onnx` + `*.onnx.json` | Voces TTS instaladas por el usuario (override sobre las bundled). | usuario (drop manual). |
| `%APPDATA%/Origin/logs/origin.log` | Log rotativo. `RotatingFileHandler` 5MB × 3 backups. | `logging_setup.setup`. |
| `%APPDATA%/Origin/.lock` | `QLockFile` single-instance. | `ui/app.py:_single_instance_lock`. |
| `%APPDATA%/Origin/piper/piper.exe` | Override de Piper en dev (si no hay bundle). | usuario. |
| `sys._MEIPASS/piper/piper.exe` | Piper bundled (PyInstaller frozen). | build pipeline. |
| `sys._MEIPASS/voices/*` | Voces bundled. | build pipeline. |
| `sys._MEIPASS/models/Systran--faster-whisper-<size>/` | Modelo Whisper bundled. | build pipeline. |
| `sys._MEIPASS/commands.preset.yaml` | Preset copiado a `%APPDATA%` al primer arranque (`ensure_preset`). | build pipeline. |
| `sys._MEIPASS/origin/ui/i18n/{es,en}.json` | Strings UI bundled. | build. |
| `sys._MEIPASS/origin/engine/tts_phrases_{es,en}.json` | Frases TTS bundled. | build. |

En Linux/macOS dev: `%APPDATA%/Origin` → `~/.config/origin` (`paths.py:_default_base`).

## 11. Resource discovery order

`paths.py` define el orden de búsqueda. Idea: bundled gana si está frozen; dev/user puede sobreescribir.

| Recurso | Orden de búsqueda |
|---|---|
| `piper.exe` (`piper_exe_path`) | 1) `sys._MEIPASS/piper/piper.exe` si frozen — 2) `%APPDATA%/Origin/piper/piper.exe` — 3) `%APPDATA%/Origin/piper/piper` (Linux dev). Devuelve `None` si no encuentra. |
| Voces bundled (`bundled_voices_dir`) | 1) `sys._MEIPASS/voices` si frozen — 2) `<repo>/installer/voices` (dev). Las voces de usuario van aparte en `default_paths().voices_dir`. `PiperTTS._resolve_voice` chequea **user dir primero**, luego bundled. |
| Modelo Whisper (`stt._bundled_models_dir`) | Solo si frozen: `sys._MEIPASS/models/`. Pasado como `download_root` a `WhisperModel` → `faster-whisper` lo encuentra ahí en vez de bajarlo de HuggingFace en el primer arranque. |
| `commands.preset.yaml` (`__main__.ensure_preset`) | 1) `bundled_resource_dir()/commands.preset.yaml` — 2) `<repo>/commands.preset.yaml` (dev). Se copia a `%APPDATA%/Origin/commands.yaml` si no existe. |
| i18n UI (`ui/i18n/tr.py`) | `Path(__file__).parent / "{lang}.json"`. En frozen, PyInstaller lo coloca en `sys._MEIPASS/origin/ui/i18n/`. |
| TTS phrases (`engine/runtime._load_tts_phrases`) | `Path(__file__).parent / "tts_phrases_{lang}.json"`. Mismo patrón. |

## 12. Hot-reload

`watchdog.observers.Observer` monitorea el directorio de `commands.yaml` (recursive=False). Handler debouncea con 300ms via `threading.Timer` para colapsar saves rápidos (la mayoría de editores hacen write+rename y disparan 2-3 eventos).

`reload_config` (`runtime.py:295`):
1. Re-parsea con `cfgmod.load`. Si falla → `CONFIG_ERROR` banner, return.
2. Bajo `_state_lock`: swap `self._cf`, `self._settings`. `ProfileRegistry.replace_config` actualiza su matcher cache; si el perfil activo desapareció, cae al `active_profile` del nuevo settings o al primero.
3. Limpia `_script_states[k]` para perfiles que ya no existen. **Los `vars` de perfiles que siguen existiendo se preservan** — un comando con `set: count` no pierde el contador por un save del YAML.
4. Emite `CONFIG_RELOADED`. UI re-pinta combo de perfiles y muestra banner info.

No se rebuildean Whisper, Piper, listeners de teclado/HOTAS — eso lo hace `set_setting` cuando el cambio viene desde la UI (que conoce qué subsistemas tocar). Si el usuario edita `whisper_model` a mano en el YAML, el hot-reload actualiza `self._settings` pero el `Transcriber` sigue con el modelo viejo cargado hasta que se rebuildee desde Settings.

## 13. Internacionalización (dos sistemas separados)

**Por qué dos**: el engine no puede depender del módulo i18n de la UI (es sin Qt y testeable headless). Las frases que dice el engine vía `SayKeyStep` necesitan vivir junto al engine. Mantener separados evita import cycles y permite a un futuro frontend distinto reusar el engine sin las strings de Qt.

| Sistema | Ubicación | Cargado por | Uso | Fallback |
|---|---|---|---|---|
| **UI i18n** | `origin/ui/i18n/{es,en}.json` | `ui/i18n/tr.py:load(lang)` | `tr("sidebar.dashboard")` en widgets. Páginas se registran via `register_retranslatable(callback)` para repintar en cambio de idioma. | clave en EN faltante → ES, ES faltante → key raw. |
| **Engine TTS phrases** | `origin/engine/tts_phrases_{es,en}.json` | `runtime._load_tts_phrases(lang)` al construir Orchestrator. | `SayKeyStep(key="tts.target_locked")` → busca en el dict del idioma activo. | Si falta → `"[missing:key]"` (no crashea, visible para debugging). |

El idioma de la UI (`ui_language`) y el idioma activo de voz/STT (`active_language`) son independientes: podés tener la GUI en EN y hablarle en ES.

## 14. Build pipeline

`installer/build_installer.ps1` orquesta 4 pasos (Windows-only — el script es PowerShell):

| Paso | Acción | Salida | Idempotente |
|---|---|---|---|
| [0/3] | Descarga `piper_windows_amd64.zip` de `github.com/rhasspy/piper/releases/<PiperVersion>`, expande en `installer/piper/`. Descarga voces ONNX (`es_ES-mls_10246-low`, `en_US-amy-low`) de `huggingface.co/rhasspy/piper-voices` a `installer/voices/`. Skip con `-SkipPiper`. | `installer/piper/piper.exe`, `installer/voices/*.onnx{,.json}` | Sí, chequea `Test-Path`. |
| [1/4] | `uv run python -c "from huggingface_hub import snapshot_download..."` baja el modelo Whisper `Systran/faster-whisper-<Model>` a `installer/models/`. Soporta `-Model {tiny,base,small,medium,large-v3}`, default `small`. | `installer/models/Systran--faster-whisper-<size>/` | Sí, skip si la carpeta tiene contenido. |
| [2/4] | `uv run pyinstaller installer/origin.spec --noconfirm` (onedir mode). Limpia `build/` y `dist/` antes para evitar caches viejos. | `dist/Origin/Origin.exe` + DLLs + datas (~700 MB para small). | No (full rebuild). |
| [3/4] | `ISCC.exe installer/origin.iss` compila el instalador. Si `ISCC.exe` no está en `$IsccPath` (default `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`), warning y skip. | `dist/OriginSetup-<version>-<model>-v3.exe` (~250 MB). | No. |

PyInstaller spec (`installer/origin.spec`):

```python
datas = [
    (root / "origin/ui/i18n/es.json",         "origin/ui/i18n"),
    (root / "origin/ui/i18n/en.json",         "origin/ui/i18n"),
    (root / "origin/ui/assets",                "origin/ui/assets"),
    (root / "origin/engine/tts_phrases_es.json", "origin/engine"),
    (root / "origin/engine/tts_phrases_en.json", "origin/engine"),
    (root / "commands.preset.yaml",            "."),
]
if (root / "installer/models").exists():  datas.append((root/"installer/models",  "models"))
if (root / "installer/piper").exists():   datas.append((root/"installer/piper",   "piper"))
if (root / "installer/voices").exists():  datas.append((root/"installer/voices",  "voices"))

hiddenimports = [
    "ctranslate2", "faster_whisper", "sounddevice._sounddevice",
    "pydirectinput", "pynput.keyboard._win32", "pynput.mouse._win32",
    "tokenizers", "watchdog.observers.read_directory_changes",
    "watchdog.observers.winapi", "httpx", "inputs",
]
excludes = ["tkinter", "matplotlib", "scipy"]
```

`console=False` para que no flote consola al lanzar el .exe.

Inno Setup (`installer/origin.iss`):
- `DefaultDirName={localappdata}\Programs\Origin` (sin admin: `PrivilegesRequired=lowest`, `PrivilegesRequiredOverridesAllowed=dialog`).
- AppId GUID fijo `{8C7F0A1F-2A5A-4D6D-9C2F-7B5E2A0C9F00}` — upgrade in-place entre versiones.
- Task opcional `autostart` (unchecked por default) que escribe `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Origin = "<app>\Origin.exe" --tray`.
- Task `desktopicon`.
- Compresión `lzma2 + SolidCompression=yes`.
- Idiomas del instalador: inglés y español.

CI (`.github/workflows/origin-release.yml`):
- **Trigger**: push de tag `origin-v*` o `workflow_dispatch` con choice de modelo.
- **Runner**: `windows-latest`, Python 3.12, `uv sync --extra dev`.
- **Cache**: `actions/cache@v4` con key `whisper-<MODEL>-v1` para no re-bajar el modelo Whisper de HuggingFace cada run.
- **Steps**: checkout → setup-python → setup-uv → `uv sync --extra dev` → cache restore → `choco install innosetup --yes` → `pwsh installer/build_installer.ps1 -Model $env:MODEL` → upload artifact siempre.
- **Release**: solo si tag, `softprops/action-gh-release@v2` con `generate_release_notes: true`.
- **Concurrency**: `group: origin-release-${{ github.ref }}`, `cancel-in-progress: false` (tags distintos no se cancelan, manuales sobre la misma ref sí).
- **Timeout**: 60 min (el build de `large-v3` puede tomar 40+ min entre download del modelo + compilación).

Versionado: el `version` está duplicado en `pyproject.toml`, `origin/__init__.py` (`__version__`), y `installer/origin.iss` (`#define AppVersion`). Hay que actualizarlos los tres al bumpear.

## 15. Tests

119 tests `def test_*` distribuidos:

- **Engine** (~78): `tests/engine/test_*.py`. Cobertura por módulo:
  - `test_config.py` / `test_config_v3.py`: schema, validators, `with_settings`, `save_atomic` atomicity.
  - `test_migration_v1_v2.py`: migraciones, backups idempotentes.
  - `test_intent.py`: normalización, fuzzy score, filtrado por idioma.
  - `test_keypress.py`: `parse_combo` con todos los aliases, `validate`, modificadores duplicados, combos solo-modificador.
  - `test_tts.py`: spawn de piper mockeado, cancel, voice resolution (user > bundled).
  - `test_llm.py`: prompt assembly, validación de respuesta, filtro de IDs inválidos, max_commands.
  - `test_hotas.py`: enumeración, capture mode, binding parser.
  - `test_i18n_loader.py`: fallback a {} cuando falta archivo.
  - `test_profiles.py`: cycle, cache invalidation, replace_config con perfil activo desaparecido.
  - `test_runtime_regressions.py`: bugs históricos (mic restart con captura en vuelo, state stuck tras Test, etc.).
  - `test_script_executor.py`: eval_cond, goto a label inexistente, MAX_STEPS, repeat × times con cancel.
  - `test_events.py`: subscribe/unsubscribe, listener excepción no rompe a otros.
  - `test_autostart_windows.py`: skipea si no es Windows, mockea `winreg`.
  - `test_preset.py`: el preset bundled valida contra el schema v3.
- **UI** (~44, marker `gui`): `tests/ui/test_*.py` con `pytest-qt` + `QtBot`. Cubren `main_window`, `commands_editor`, `profiles_manager`, `script_editor`, `settings_language_toggle`, `settings_ptt_capture`, `tray`. Requieren `QT_QPA_PLATFORM=offscreen` para correr headless en CI.

Comandos:

```bash
pytest tests/                    # todo (necesita display o offscreen)
pytest tests/engine/             # solo engine, no necesita Qt
pytest -m "not gui"              # excluye marker gui
QT_QPA_PLATFORM=offscreen pytest tests/ui/
pytest -k "test_intent" -v       # un módulo específico
```

Battery exploratoria/ad-hoc en `/tmp/ultra_audit.py` con ~50 escenarios end-to-end (PTT-down → audio sintético → match → dispatch → assert estado final). No corre en CI; sirve como smoke pre-release.

Mocks típicos:
- `pydirectinput` no instalado en Linux → `keypress._get_pdi()` retorna `None`, `execute` loguea warning y no envía; los tests verifican el log o mockean directamente `_get_pdi`.
- `inputs` (HOTAS) — `tests/engine/test_hotas.py` inyecta un fake `gamepads` list con event streams custom.
- `winreg` (autostart) — `test_autostart_windows.py` mockea o skipea si no es Windows.
- `httpx` mockeado con `pytest-httpx` para LLM (verifica request body, fake responses).
- `sounddevice` mockeado con `unittest.mock` para no requerir PortAudio en CI.
- `Whisper` raramente se carga en tests — `Transcriber` se mockea para que `transcribe` devuelva strings determinísticos.

## 16. Decisiones arquitectónicas con tradeoffs

| Decisión | Por qué | Tradeoff |
|---|---|---|
| Engine sin Qt | Testabilidad headless en CI Linux; reusabilidad para frontend alternativo. | Bridge layer (`EngineBridge`) explícito; emisores en threads no-UI exigen `QueuedConnection`. |
| `EventBus` propio en vez de `QSignal` directo | Igual razón ↑; emit es no-bloqueante y sin GIL contention con Qt. | Subscriber roto puede bloquear emisor (mitigado con try/except por listener). |
| PyInstaller **onedir**, no onefile | Onefile desempaqueta a `%TEMP%` en cada cold-start; con modelo Whisper de 240-3000 MB son 5-30s extra. Onedir cold-start < 2s. | Instalador "más sucio" (carpeta con DLLs) — aceptable, está en `Programs\Origin`. |
| `piper.exe` binary, **no** `piper-tts` pip package | El paquete pip arrastra ONNX runtime + DLLs que chocan con ctranslate2 en PyInstaller (DLL hell). El binary es un .exe standalone. | Spawn cost por `say()`; aceptable (~50ms). |
| `inputs` (pure Python), **no** `pygame.joystick` | `pygame` arrastra SDL2 + 80 MB de deps. `inputs` es < 50 KB pure Python sobre `XInput`. | `gp.read()` es bloqueante → un thread por device, no se puede unblock limpio (ver §18). |
| `pydirectinput` (DirectInput), **no** `keyboard`/`SendInput` | Star Citizen consume DirectInput; `keyboard` / `SendInput` no llegan al juego en ventana fullscreen. | Windows-only; tests mockean en Linux. |
| Pydantic v2 **frozen** + `extra="forbid"` | Detecta mutaciones accidentales (Pydantic levanta `ValidationError`); typos en YAML son loud. | `with_settings(**changes)` requiere `model_copy` explícito; un poco más verboso. |
| `ThreadPoolExecutor(max_workers=1)` para STT | El modelo de Whisper no es thread-safe entre `transcribe()` concurrentes (`stt.py:46`). Un solo worker serializa de forma natural y respeta el orden de PTTs. | Si llega un PTT mientras un comando aún ejecuta, queda como `ptt_busy`; aceptable para el use-case (PTT discreto). |
| Hot-reload con debounce 300ms | La mayoría de editores hacen write+rename → 2-3 eventos. Debounce evita doble-load. | Cambios consecutivos a < 300ms se colapsan en uno. |
| `save_atomic` (tmp + rename) | Si el proceso muere a mitad del write, el YAML viejo queda intacto. | Trivial overhead (`os.replace` es atómico en NTFS). |
| Voces TTS y modelo Whisper **bundled** en el installer | Sin internet en el primer arranque, app usable inmediato. | Instalador pesa ~600 MB (small) hasta ~3.5 GB (large-v3). |

## 16.1 Patrones recurrentes en el código

Para no sorprenderte al leer:

- **Imports lazy en funciones**: `pynput`, `sounddevice`, `faster_whisper`, `watchdog`, `pydirectinput`, `inputs`, `winreg` se importan dentro de la función que los usa (no a nivel módulo). Razón: permitir que el módulo cargue en CI Linux sin tener las deps nativas.
- **`# lazy` comment** marca el import lazy.
- **`# type: ignore[import-untyped]`** en deps sin stubs (`watchdog`, `pydirectinput`, `inputs`, `ctranslate2`).
- **Mensajes de log estilo logfmt**: `"transcription_failed elapsed=%dms"` — fácil de grepear y parsear, soportado por el formatter JSON opcional.
- **`_state_lock` es RLock**: para soportar reentradas. Ej: `_dispatch_command` corre dentro de un bloque que ya tomó el lock, y llama `_set_state` que lo toma de nuevo.
- **`threading.Event` para cancel cooperativo**: `_script_cancel`, `_cancel` en TTS, `_stop` en HOTAS. Patrón uniforme: `event.set()` desde el cancelador, polling regular desde el worker.
- **Métodos bound como callbacks**: en `_build_script_executor` se pasan `self._tts_say`, `self._tts_cancel_indirect` (no `self._tts.say` directo) — así si `self._tts` se rebuildea, el lookup en runtime sigue válido (`runtime.py:635`).
- **`finally` para state cleanup**: cualquier método que cambia de state hace el revert en `finally` para sobrevivir excepciones (`execute_command_test`, `_dispatch_command`, `_say`).
- **Emit de eventos siempre fuera del lock**: para no bloquear emisores mientras subscribers procesan.

## 17. Cosas que NO funcionan en Linux

Origin es Windows-first. Estos módulos están condicionados o stubeados:

- `pydirectinput` — declarado `; sys_platform == 'win32'` en `pyproject.toml`. `keypress._get_pdi()` retorna `None` en Linux y `execute()` loguea warning sin enviar nada.
- `inputs` — idem; `HotasListener.start` retorna sin hacer nada si `_try_import_inputs` devuelve `None`.
- `autostart_windows` — `is_supported()` chequea `sys.platform == "win32"`; todas las funciones son no-op.
- `pynput.keyboard._win32` — el listener funciona en Linux con `_xorg` pero hace falta server X corriendo. CI lo skipea por marker `gui`.
- `winreg` — import condicional dentro de las funciones que lo necesitan.

Imports lazy en `runtime.py`: `pynput.keyboard`, `sounddevice`, `watchdog`, `faster_whisper`. Esto permite que tests de configuración carguen sin tener las deps nativas instaladas.

## 17.1 Páginas y widgets de la UI (mapa rápido)

Para fixear un bug de GUI, este es el mapa de archivos:

| Archivo | Rol |
|---|---|
| `origin/ui/app.py` | Bootstrap: QApplication, single-instance lock, instancia Orchestrator + EngineBridge + MainWindow + Tray, wire del hot-reload de tema/idioma. |
| `origin/ui/main_window.py` | Sidebar + header (state dot, lang toggle, profile combo, pause btn) + `QStackedWidget` con las 6 páginas + banner de avisos. |
| `origin/ui/tray.py` | `QSystemTrayIcon` + menú dinámico (perfil/idioma/pause se reflejan en vivo via signals). Icono pintado programáticamente con `QPainter` (sin assets externos). |
| `origin/ui/engine_bridge.py` | QObject que subscribe al `EventBus` y re-emite Qt signals. Único punto de cruce thread→UI. |
| `origin/ui/theme.py` | `apply_theme(app, "system"|"light"|"dark")` con QSS embebido. |
| `origin/ui/pages/dashboard.py` | VU meter, transcription log, latencias últimos 10 STT/match, pause btn. |
| `origin/ui/pages/commands_editor.py` | `QTableWidget` con auto-save por celda. Phrases y keys son comma-separated. Validación inline (borde rojo + tooltip). |
| `origin/ui/pages/profiles_manager.py` | CRUD de perfiles, duplicate, set-active, import/export. |
| `origin/ui/pages/settings.py` | Forms con todos los settings, agrupados (audio, whisper, ui, tts, hotas, llm, autostart). 623 líneas — el archivo más grande de la UI. |
| `origin/ui/pages/logs_viewer.py` | Tail vivo de `origin.log` con filtro por level. |
| `origin/ui/pages/about.py` | Version, links, build info. |
| `origin/ui/widgets/vu_meter.py` | Barra de nivel logarítmica con peak hold. |
| `origin/ui/widgets/fuzz_slider.py` | Slider de threshold + preview del top-5 matches en vivo contra una transcripción de prueba. |
| `origin/ui/widgets/key_capture.py` | Captura una tecla / combo press desde el usuario (PTT key, profile hotkey). |
| `origin/ui/widgets/script_editor.py` | Editor visual del DSL — step types planos. Para `if`/`repeat`, editar YAML. |
| `origin/ui/widgets/transcription_log.py` | Lista de últimas N transcripciones con timestamp y score. |
| `origin/ui/i18n/{es,en}.json` | Strings de la GUI. Key flat (`"sidebar.dashboard": "Dashboard"`). |
| `origin/ui/i18n/tr.py` | `tr()`, `load()`, `retranslate_all()`. |

## 17.2 Dónde tocar para... (mapa de cambios comunes)

| Cambio | Archivos clave |
|---|---|
| Agregar un step type nuevo al DSL | `engine/config.py` (modelo + agregar al Union `Step`), `engine/script.py:_exec_one` (manejo), `ui/widgets/script_editor.py` (UI). Validar con un test en `tests/engine/test_script_executor.py`. |
| Agregar un setting nuevo a `Settings` | `engine/config.py:Settings` (campo Pydantic) + `commands.preset.yaml` (valor default explícito) + `ui/pages/settings.py` (form widget). Si tiene efecto en runtime, agregar branch en `runtime.set_setting`. |
| Agregar un EventType nuevo | `engine/events.py:EventType` (literal), `ui/engine_bridge.py` (Signal + subscriber), consumer en la página relevante. |
| Soportar un juego nuevo | Cambiar el preset `commands.preset.yaml` (perfiles + comandos). El motor es game-agnostic, solo cambia el catálogo. Si requiere keybinds no-DirectInput, hay que extender `keypress`. |
| Soportar una voz TTS nueva | Bajar `voice.onnx` + `voice.onnx.json` a `%APPDATA%/Origin/voices/` (override) o agregar al `build_installer.ps1` paso [0/3] (bundled). Configurar `tts.voice_es`/`voice_en` en settings. |
| Cambiar el LLM | `settings.llm.model` + `ollama pull <model>`. Si el modelo no respeta `format: json`, ajustar `_prompt_system` para reforzar. Para usar otro provider distinto a Ollama, reescribir `OllamaClient.chat_json` con la API correspondiente. |
| Bumpear versión | `pyproject.toml`, `origin/__init__.py`, `installer/origin.iss` (`#define AppVersion`). Tag `git tag origin-vX.Y.Z && git push --tags` dispara CI. |
| Agregar una página a la UI | Crear `ui/pages/foo.py` con `class FooPage(QWidget)`. Agregar a `SIDEBAR` en `main_window.py` y al dict `_pages`. Strings en `i18n/{es,en}.json`. |
| Cambiar el threshold default | `engine/config.py:Settings.fuzz_threshold = Field(default=75, ...)`. Existing users no se ven afectados (default solo aplica a configs nuevas). |
| Investigar un bug "no envía teclas" | Verificar `keypress.execute` logs (`pydirectinput no disponible` o `dry_run keys=[...]`). Star Citizen en ventana sin foco no recibe input — DirectInput requiere foco activo. |
| Investigar un bug "no transcribe" | Logs `model_load_failed`, `transcription_failed`, `cuda_failed_downgrading_to_cpu`. `Transcriber._warm_up` debe completar antes del primer PTT — si el state se queda en `LOADING` es eso. |
| Investigar "PTT ignorado" | Logs `ptt_press_ignored state=X` o `ptt_busy state=X`. Estado `BUSY` o `PAUSED/LOADING/ERROR`. |

## 18. Limitaciones conocidas v0.3

- **HOTAS thread leak al rebindear**: `HotasListener.stop()` setea el event pero `gp.read()` queda bloqueado hasta el próximo evento del device. El thread es daemon, muere con el proceso, pero rebindes en runtime acumulan threads zombie hasta cerrar la app. Workaround: cerrar y reabrir Origin tras cambiar `hotas.button_binding` repetidas veces.
- **No mouse input**: `pydirectinput` soporta mouse pero el DSL solo expone `KeyStep`. Comandos que requieren clic deben hacerse con macros del juego.
- **Hold-key solo via step explícito**: `KeyStep(combo="b", hold_ms=500)` funciona; el PTT en sí es tap (la "duración" del PTT marca solo la ventana de grabación, no se traduce a hold-key).
- **LLM requiere Ollama corriendo aparte**: no hay LLM embebido. El usuario debe instalar Ollama, hacer `ollama pull llama3.1:8b` (o el modelo configurado), y dejar el servicio escuchando en `base_url`. Sin Ollama → preflight banner, fallback silencioso (mejor score < threshold → no acción).
- **Sub-steps de `if`/`repeat` NO editables desde `ScriptEditorDialog`**: el editor visual maneja step types planos (key/wait/say/say_key/set/goto/label). Para `if.then`, `if.else`, `repeat.steps` hay que editar `%APPDATA%/Origin/commands.yaml` a mano. El hot-reload toma el cambio al guardar (`origin/ui/widgets/script_editor.py:1-9`).
- **Solo `IfStep` y `RepeatStep` se cuentan en `MAX_STEPS_PER_COMMAND`**: `goto` que crea loop sin `repeat` se atrapa en runtime (`_steps_run >= 100`), no en validación de config. Síntoma: comando se corta a mitad con `script_step_limit_reached` en logs.
- **`watchdog` en Linux con NFS**: no detecta cambios en filesystems no-inotify. `import` opcional, se desactiva con log `watchdog_unavailable hot_reload_disabled`.
- **Cambio de mic device durante grabación se descarta**: `Recorder.restart_stream` limpia el buffer en vuelo intencionalmente (sin esto mezclaba audio de mic viejo + nuevo). Usuario pierde la grabación parcial — aceptable y poco común.
- **State `EXECUTING` es legado v0.2**: aparece en la enum pero el runtime v0.3 lo cubre con `RUNNING_SCRIPT`. Solo se setea desde `execute_command_test` cuando el comando viene del botón Test del editor — el state final tras el test vuelve a `READY` en `finally`.
