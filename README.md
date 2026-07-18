# Origin — asistente de voz bilingüe para Star Citizen

App de escritorio para Windows que escucha comandos por **Push-to-Talk** (PTT), los transcribe localmente con **faster-whisper** y los traduce a combinaciones de teclas DirectInput. Bilingüe **ES/EN** (toggle activo), **perfiles múltiples** (Flight, FPS, EVA, Mining, …), dashboard con PySide6, persistencia en `commands.yaml` editable a mano, y system tray para quedarse en background mientras jugás.

**Sin Internet** después de la primera descarga del modelo. Sin telemetría. Sin pagos por API.

## Novedades

- **Head tracking por webcam (nuevo)** — convertí tu webcam común en un head-tracker (misma idea que Beam Eye Tracker): estima la pose 6DoF de tu cabeza y la manda a **OpenTrack** para tener *head-look* en Star Citizen (mirar la cabina/espejos moviendo la cabeza, sin TrackIR). Además, **gestos de cabeza** (cabecear, negar, inclinar, acercarse) pueden disparar comandos del perfil. Página "Cabeza" en la GUI con pose en vivo, calibración, sensibilidad por eje y bindings de gestos. Usa MediaPipe + OpenCV (Windows); el engine y los tests corren en Linux con un backend mock.

## Novedades v0.3

- **TTS local con Piper** — Origin te responde por voz tras matchear ("hangar solicitado, capitán"). Una voz fija ES + una EN configurables; bundle del `.exe` incluye `piper.exe` + 2 modelos ONNX.
- **PTT por botón de HOTAS / joystick** — librería `inputs`, capture-by-press en Settings. Funciona en paralelo con la tecla PTT.
- **Fallback LLM con Ollama** — cuando ningún comando matchea por fuzzy pero la transcripción no está vacía, un LLM local interpreta intent free-form ("prepará entrada a Crusader" → secuencia de comandos). Opt-in, requiere `ollama serve` corriendo.
- **Scripting DSL** — cada comando puede declarar `steps:` con tipos `key`, `wait`, `say`, `set`, `if`, `goto`, `label`, `repeat`. Backward compatible: `keys:` legacy sigue funcionando.
- **Preset 200+ comandos** — 10 perfiles bilingües: flight, mobiglas, fps, eva, mining, quantum, combat, salvage, refuel_cargo, voice_misc.
- **3 estados nuevos en el dashboard**: `running_script`, `speaking`, `resolving_intent`.

---

## Quickstart (Windows 11)

```powershell
# Requiere uv (https://github.com/astral-sh/uv) y Python 3.10–3.12.
cd origin
uv sync                  # ~45 s

# Lanzar GUI (default)
uv run python -m origin

# CLI sin GUI (engine puro, headless)
uv run python -m origin --headless

# Dry-run (loguea las teclas pero no las envía)
uv run python -m origin --dry-run

# Listar micrófonos disponibles
uv run python -m origin --list-mics
```

El primer arranque copia [`commands.preset.yaml`](commands.preset.yaml) a `%APPDATA%\Origin\commands.yaml` y empieza a cargar el modelo Whisper en background. La ventana abre en **Dashboard**.

> SC corre con EAC (Easy Anti-Cheat). Para que `pydirectinput` pueda enviar teclas mientras SC está enfocado, **lanzá Origin desde una terminal con permisos de administrador** (o instalalo con el `.exe` empaquetado e indicalo en las propiedades del shortcut).

---

## Tour por la GUI

### Panel (Dashboard)
- Estado del motor (cargando modelo / listo / grabando / transcribiendo / pausado / error).
- VU meter en vivo del micrófono.
- Últimas 10 transcripciones con su match (verde = matched, rojo = sin match).
- Latencia promedio (STT + matching + total).
- Botón grande de Pausar / Reanudar.

### Comandos
- Selector de perfil arriba.
- Tabla editable con `id`, frases ES, frases EN, teclas, etiquetas y descripciones.
- Frases y teclas en formato **comma-separated** dentro de la celda (ej.: `pide hangar, solicita aterrizaje`).
- **Probar comando** ejecuta las teclas tras 3 s para que hagas alt-tab al juego — útil para verificar binds reales.
- Auto-save con debounce 500 ms; validación inline (id duplicado pinta rojo).

### Perfiles
- CRUD + duplicar + importar (un perfil YAML) + exportar.
- Renombrar etiquetas ES/EN y descripciones desde el panel derecho.
- Borrar el perfil activo fallbackea al primero restante (mínimo un perfil debe existir).

### Ajustes
- **Atajos**: tecla PTT (capturada presionando), hotkey de cambio de perfil (combo con modificadores).
- **Whisper**: modelo (`tiny`/`base`/`small`/`medium`/`large-v3`), device (auto/cpu/cuda — `cuda` se deshabilita si no está disponible), compute type.
- **Audio**: micrófono (dropdown poblado con `sounddevice`), sample rate, duración máxima de grabación.
- **Reconocimiento**: umbral fuzzy 0–100 con **preview en vivo** (tipeás una frase y ves qué comandos del perfil activo matchearían), delay entre teclas.
- **UI**: idioma de la interfaz (ES/EN), tema (sistema/claro/oscuro).
- **Inicio**: iniciar con Windows (HKCU run key), arrancar minimizado al tray.
- **Logs**: formato (pretty/json), abrir carpeta de logs.

### Registros
Tail incremental del archivo de log con filtro por nivel y búsqueda.

---

## Bilingüe ES/EN

El idioma activo se elige desde el header (`ES | EN`) o el menú del tray. **No hay auto-detect**: Whisper se invoca con `language="es"` o `language="en"` explícito, y el matcher solo evalúa las frases del idioma activo. Cada comando declara `phrases_es` y `phrases_en` por separado.

```yaml
- id: request_landing
  phrases_es: ["pide hangar", "solicita aterrizaje"]
  phrases_en: ["request landing", "request hangar"]
  keys: ["alt+n"]
```

---

## Perfiles

Cada perfil es un set independiente de comandos para un contexto del juego (Flight, FPS, EVA, Mining, Quantum, …). Solo se evalúan los comandos del **perfil activo**. Cambiá de perfil:

- desde el dropdown del header,
- desde el menú del tray,
- con el hotkey configurable (default `Ctrl+F12`, que cicla al siguiente perfil).

El perfil activo al PTT-press se snapshotea: si cambiás de perfil durante la grabación, el match se hace contra el perfil snapshoteado y el nuevo aplica al siguiente PTT.

---

## Formato de `commands.yaml`

Vive en `%APPDATA%\Origin\commands.yaml`. Hot-reload externo: si lo editás en VS Code, el watchdog detecta el cambio y recarga en <1 s. Si el YAML queda inválido, la UI muestra un banner rojo y el engine sigue corriendo con la última config válida.

Schema completo: ver [`commands.preset.yaml`](commands.preset.yaml). Resumen de teclas válidas:

- Letras `a-z`, dígitos `0-9`.
- Funciones `f1`..`f24`.
- Especiales: `enter`, `space`, `tab`, `escape`/`esc`, `backspace`, `delete`/`del`, `up`/`down`/`left`/`right`, `home`, `end`, `pageup`/`pgup`, `pagedown`/`pgdn`, `insert`/`ins`.
- Modificadores: `ctrl`, `shift`, `alt`, `win`/`super`/`cmd`.
- Combos: `alt+n`, `ctrl+shift+x`. Secuencias: `["alt+n", "y"]` con delay configurable entre teclas.

> **Limitación v0.2**: solo taps (keyDown+keyUp atómico). No hay hold-key para "sprint" o "EVA strafe up". Para eso necesitarías reconocimiento continuo, que está fuera de scope.

> **No mouse**: `pydirectinput` solo emite teclado en este momento. Rebindeá las acciones que usan mouse a teclas en SC.

Migración v1 → v2: si tu archivo es v1 (formato plano sin perfiles), se migra automáticamente a un perfil único `default` y se guarda backup en `commands.v1.backup.yaml`.

---

## Privacidad

- Audio: capturado, transcrito **localmente** con faster-whisper, descartado. Nunca sale de la máquina.
- Modelo Whisper: descarga 1 vez (HuggingFace, repo `Systran/faster-whisper-<size>`) y se cachea en `~/.cache/huggingface/` (dev) o en el bundle del instalador.
- Telemetría: cero.

---

## Empaquetado (instalador .exe)

```powershell
# Una sola vez: instalar Inno Setup 6 (https://jrsoftware.org/isinfo.php)
# Build pipeline:
pwsh installer/build_installer.ps1                # modelo small por default
pwsh installer/build_installer.ps1 -Model medium  # modelo más grande
```

Genera `dist/OriginSetup-0.2.0-small.exe` (~600 MB con `small`). El instalador:

- usa `%LOCALAPPDATA%\Programs\Origin\` (sin admin),
- ofrece checkbox de "Iniciar con Windows" (escribe HKCU),
- crea atajos en escritorio y menú inicio,
- registra desinstalador.

Bajo el hood: PyInstaller (modo `onedir`) + Inno Setup. El modelo Whisper queda **embebido en el bundle** para que el primer arranque no necesite Internet.

### Build automatizado en CI

GitHub Actions (`.github/workflows/origin-release.yml`) corre el pipeline en `windows-latest`:

```bash
# Empaqueta y publica en Releases automáticamente
git tag origin-v0.2.0
git push origin origin-v0.2.0
```

También se puede disparar manualmente desde la pestaña Actions ("Run workflow") eligiendo el tamaño de modelo. El workflow cachea el modelo Whisper entre runs (no re-descarga 485 MB cada vez), instala Inno Setup vía Chocolatey, sube el `.exe` como artifact y lo adjunta al GitHub Release cuando el trigger es un tag `origin-v*`.

---

## Arquitectura

```
origin/
├── pyproject.toml
├── commands.preset.yaml           # preset bilingüe que se copia a %APPDATA% el primer arranque
├── installer/                     # PyInstaller spec + Inno Setup script + build pipeline
├── origin/
│   ├── __main__.py                # CLI: --headless, --tray, --config, --list-mics, --dry-run
│   ├── engine/                    # SIN Qt: usable headless. EventBus + threading.
│   │   ├── config.py              # Pydantic v2 + migración v1→v2 + save_atomic
│   │   ├── audio.py               # sounddevice InputStream + RMS para VU + ventanas de captura
│   │   ├── stt.py                 # faster-whisper lazy load + warm-up + downgrade CUDA→CPU
│   │   ├── intent.py              # rapidfuzz.token_set_ratio + normalización (NFKD + lowercase)
│   │   ├── keypress.py            # pydirectinput lazy: parse_combo + execute + validate
│   │   ├── profiles.py            # ProfileRegistry: active + matcher cacheado por perfil
│   │   ├── runtime.py             # Orchestrator: PTT + state machine + watchdog hot-reload
│   │   ├── events.py              # EventBus thread-safe (sin dependencia de Qt)
│   │   ├── paths.py               # %APPDATA%/Origin/{commands.yaml,settings.json,logs/}
│   │   └── autostart_windows.py   # HKCU run key vía winreg (no-op en otros SO)
│   └── ui/                        # PySide6. Depende del engine; el engine NO depende de la UI.
│       ├── app.py                 # QApplication bootstrap + single-instance lock + tray init
│       ├── engine_bridge.py       # EventBus → Qt signals (QueuedConnection cross-thread)
│       ├── main_window.py         # sidebar + header + QStackedWidget + banner
│       ├── tray.py                # QSystemTrayIcon con menú dinámico (perfil/idioma/estado)
│       ├── theme.py               # light/dark/system (QStyleHints.colorScheme())
│       ├── pages/                 # 6 páginas: dashboard, commands, profiles, settings, logs, about
│       ├── widgets/               # vu_meter, key_capture, fuzz_slider, transcription_log
│       └── i18n/                  # es.json + en.json + tr(key) helper con fallback a ES
└── tests/                         # pytest engine (sin Qt) + pytest-qt UI (`pytest -m "not gui"` en CI)
```

**Contrato engine ↔ UI**: el engine publica eventos `ENGINE_STATE_CHANGED`, `AUDIO_LEVEL`, `TRANSCRIPTION_DONE`, `MATCH_DONE`, `COMMAND_EXECUTED`, `PROFILE_CHANGED`, `LANGUAGE_CHANGED`, `CONFIG_RELOADED`, `CONFIG_ERROR` por `EventBus.emit(EventType, payload: dict)`. `EngineBridge(QObject)` los re-emite como Qt signals tipadas en el main thread. La UI llama métodos directos del Orchestrator (`pause`, `resume`, `set_active_profile`, `set_active_language`, `set_setting`, `reload_config`, `execute_command_test`, `shutdown`).

**Estado del orchestrator**: `IDLE → RECORDING → TRANSCRIBING → EXECUTING → IDLE`, protegido por `threading.RLock`. PTT durante TRANSCRIBING/EXECUTING se descarta con log `ptt_busy`. PTT auto-repeat del SO durante RECORDING se ignora.

**Threading**:

| Thread | Rol |
|---|---|
| Main / UI | Qt event loop, widgets, tray |
| `pynput.keyboard.Listener` (daemon) | Hook global PTT + hotkey de cambio de perfil |
| sounddevice callback | Captura PCM + RMS (~30 Hz) |
| `ThreadPoolExecutor(max_workers=1)` | Transcripción Whisper (modelo único, reutilizado) |
| `watchdog.Observer` | Hot-reload del `commands.yaml` (debounce 300 ms) |

---

## Tests

```bash
# engine (sin Qt, rápidos)
uv run pytest tests/engine -q

# UI (requiere display real o `QT_QPA_PLATFORM=offscreen`)
QT_QPA_PLATFORM=offscreen uv run pytest tests/ui -q

# Todo
uv run pytest -q
```

Cobertura por módulo: config + migración + profiles + intent + keypress + events + i18n + autostart (engine), main_window + commands_editor + profiles_manager + key_capture + language toggle + tray (UI).

---

## Verificación end-to-end (en Windows)

1. `python --version` 3.10–3.12, `uv --version`, mic conectado, GPU NVIDIA opcional.
2. `cd origin && uv sync`.
3. `uv run python -c "import faster_whisper, pydirectinput, pynput, sounddevice, rapidfuzz, PySide6, watchdog; print('ok')"`.
4. **Primer arranque GUI**: `uv run python -m origin`. Verificá: ventana abre en Dashboard, tray icon visible, `%APPDATA%\Origin\commands.yaml` creado desde el preset, estado pasa de `loading_model` a `ready` en <5 s con `small` en CPU moderna.
5. **Listar mics**: Settings → Audio → dropdown poblado; cambiar el seleccionado.
6. **Toggle idioma**: header → click `EN`; los labels cambian; el siguiente PTT transcribe en inglés.
7. **Crear perfil**: Profiles → New profile `eva`; agregar un comando en Commands editor.
8. **Test command**: en Commands editor seleccionar fila → Test → countdown 3 s → alt-tab al juego → teclas ejecutadas.
9. **Capturar PTT**: Settings → click en PTT field → presionar `F10` → field muestra `f10`.
10. **Hot-reload externo**: editar `%APPDATA%\Origin\commands.yaml` en VS Code; el cambio aparece en <1 s.
11. **YAML inválido**: introducir error de sintaxis → banner rojo en UI; engine sigue procesando con la config previa.
12. **Smoke STT bilingüe**: F12 + "pide hangar" en ES → match `request_landing`; toggle EN, F12 + "request landing" → match `request_landing`.
13. **Minimizar a tray**: click X → ventana se oculta, toast tray, PTT sigue funcionando.
14. **Reaparecer desde tray**: click izquierdo en tray icon → ventana aparece.
15. **Pause/Resume**: tray menú → Pause → tray icon cambia a pausado, PTT no graba.
16. **Auto-start**: Settings → toggle Auto-start ON → verificar `regedit` `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Origin`.
17. **CUDA downgrade**: con CUDA configurado, desconectar GPU vía Device Manager → próxima transcripción degrada a CPU sin crash.
18. **Quit definitivo**: tray menú → Quit → proceso termina.

**Criterios de éxito**: pasos 4–18 verdes con latencia end-to-end <2 s en CPU con modelo `small`.

---

## Troubleshooting

- **SC no recibe las teclas pero el log dice que se enviaron** → terminal/exe corriendo como admin? SC con EAC requiere privilegios iguales o mayores.
- **PTT no responde** → otra app que captura globalmente `F12` (Discord screenshot, Steam, OBS). Cambiá la tecla desde Settings.
- **Whisper carga lento** → primera ejecución descarga el modelo. `small` ~485 MB. Cacheado en `~/.cache/huggingface` (dev) o bundled (instalador).
- **Antivirus alerta sobre `pynput`** → el hook global de teclado dispara heurísticas. `pynput` es OSS estable; agregá excepción.
- **Mic no aparece en el dropdown** → click "Refresh" en Settings; si seguís sin verlo, revisá permisos de micrófono de Windows.
- **CUDA no disponible** → CUDA Toolkit + cuDNN + ctranslate2 con soporte CUDA. Si falla, dejá `device: auto` y va a CPU.

---

## Licencia

Apache-2.0.
