# PyInstaller spec — modo onedir.
# Construir desde la raíz del paquete:
#   pyinstaller installer/origin.spec --noconfirm
#
# El script build_installer.ps1 hace además:
#   1) descarga el modelo Whisper a installer/models/
#   2) corre pyinstaller con este spec
#   3) compila el instalador con Inno Setup (installer/origin.iss)
# - mode = "onedir" (no "onefile") porque el modelo Whisper (~240MB para small)
#   se desempaqueta a %TEMP% en cada cold-start con onefile → 5-15s extra.
# - hiddenimports cubren backends nativos que PyInstaller no detecta del grafo.
# - datas: i18n, assets, preset YAML y modelo Whisper (cargados en disco).

from pathlib import Path

block_cipher = None
root = Path.cwd()

datas = [
    (str(root / "origin" / "ui" / "i18n" / "es.json"),         "origin/ui/i18n"),
    (str(root / "origin" / "ui" / "i18n" / "en.json"),         "origin/ui/i18n"),
    (str(root / "origin" / "ui" / "assets"),                    "origin/ui/assets"),
    (str(root / "origin" / "engine" / "tts_phrases_es.json"),  "origin/engine"),
    (str(root / "origin" / "engine" / "tts_phrases_en.json"),  "origin/engine"),
    (str(root / "commands.preset.yaml"),                        "."),
]

# Modelo Whisper pre-descargado.
models_dir = root / "installer" / "models"
if models_dir.exists():
    datas.append((str(models_dir), "models"))

# Piper TTS + voces ONNX pre-descargados por build_installer.ps1 paso [0/4].
piper_dir = root / "installer" / "piper"
voices_dir = root / "installer" / "voices"
if piper_dir.exists():
    datas.append((str(piper_dir), "piper"))
if voices_dir.exists():
    datas.append((str(voices_dir), "voices"))

hiddenimports = [
    "ctranslate2",
    "faster_whisper",
    "sounddevice",
    "sounddevice._sounddevice",
    "pydirectinput",
    # pynput completo — los backends _win32 se resuelven dinámicamente en
    # runtime y PyInstaller pierde algunos si solo listamos submódulos.
    "pynput",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "tokenizers",
    "rapidfuzz",
    "watchdog.observers.read_directory_changes",
    "watchdog.observers.winapi",
    # httpx y su cadena: httpcore resuelve el backend (h11) por import dinámico,
    # que el análisis estático de PyInstaller puede perder.
    "httpx",
    "httpcore",
    "h11",
    "anyio",
    "sniffio",
    "certifi",
    "inputs",
    # pydantic v2: el core compilado a veces requiere hint explícito.
    "pydantic",
    "pydantic_core",
    "yaml",
]

a = Analysis(
    ["origin/__main__.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Origin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(root / "origin" / "ui" / "assets" / "icon.ico") if (root / "origin" / "ui" / "assets" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Origin",
)
