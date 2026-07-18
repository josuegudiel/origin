"""Auto-start vía HKCU\\...\\Run. Solo Windows; en otros SO las funciones son no-op."""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Origin"


def _exe_command() -> str:
    """Comando a registrar: el .exe empaquetado o `python -m origin` en dev."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    return f'"{sys.executable}" -m origin --tray'


def is_supported() -> bool:
    return sys.platform == "win32"


def write_run_key() -> None:
    if not is_supported():
        return
    import winreg  # type: ignore[import-not-found]

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, _exe_command())


def remove_run_key() -> None:
    if not is_supported():
        return
    import winreg  # type: ignore[import-not-found]

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    if not is_supported():
        return False
    import winreg  # type: ignore[import-not-found]

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            try:
                winreg.QueryValueEx(k, VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
    except FileNotFoundError:
        return False
