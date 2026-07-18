"""Rutas de la app. Windows → %APPDATA%/Origin. Linux/macOS dev → ~/.config/origin."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_base() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Origin"
        return Path.home() / "AppData" / "Roaming" / "Origin"
    # Linux / macOS dev fallback
    return Path.home() / ".config" / "origin"


@dataclass(frozen=True)
class AppPaths:
    base: Path

    @property
    def commands_yaml(self) -> Path:
        return self.base / "commands.yaml"

    @property
    def commands_v1_backup(self) -> Path:
        return self.base / "commands.v1.backup.yaml"

    @property
    def settings_json(self) -> Path:
        return self.base / "settings.json"

    @property
    def logs_dir(self) -> Path:
        return self.base / "logs"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "origin.log"

    @property
    def lock_file(self) -> Path:
        return self.base / ".lock"

    @property
    def voices_dir(self) -> Path:
        """Voces TTS de usuario. Se chequea aparte de las bundled."""
        return self.base / "voices"

    def ensure(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.voices_dir.mkdir(parents=True, exist_ok=True)


def default_paths() -> AppPaths:
    return AppPaths(_default_base())


def bundled_resource_dir() -> Path:
    """Carpeta de recursos empaquetados (modelo Whisper, i18n, assets, preset YAML, piper)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def piper_exe_path() -> Path | None:
    """Localiza piper.exe. None si no existe.

    SEGURIDAD (binary planting / EoP): en un build empaquetado (frozen) piper se
    resuelve EXCLUSIVAMENTE desde el bundle read-only (`sys._MEIPASS`), nunca
    desde `%APPDATA%/Origin/piper/` que es escribible por cualquier proceso del
    usuario. Sin esto, un proceso sin privilegios podía plantar un `piper.exe`
    troyano ahí y Origin lo ejecutaba — con token de admin si el usuario la
    lanzó elevada (el MANUAL lo instruye por Easy Anti-Cheat). El fallback a
    `%APPDATA%` queda SOLO para desarrollo (no-frozen), donde no hay bundle.
    """
    if getattr(sys, "frozen", False):
        c = bundled_resource_dir() / "piper" / "piper.exe"
        return c if c.exists() else None
    # Dev (no-frozen): sin bundle, buscamos en %APPDATA%.
    for c in (
        default_paths().base / "piper" / "piper.exe",
        default_paths().base / "piper" / "piper",  # linux dev
    ):
        if c.exists():
            return c
    return None


def bundled_voices_dir() -> Path | None:
    """Carpeta de voces bundled (read-only). Las del usuario van en `default_paths().voices_dir`."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(bundled_resource_dir() / "voices")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "installer" / "voices")
    for c in candidates:
        if c.exists():
            return c
    return None
