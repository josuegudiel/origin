"""Envío de teclas DirectInput vía pydirectinput.

Diseño:
- `parse_combo("alt+n")` → (["alt"], "n"). Modificadores ordenados por MODIFIER_ORDER.
- `execute([combos], inter_key_delay_ms)` envía cada combo con keyDown(mods) + press(key) + keyUp(mods reversed).
- `validate(combo)` para validación inline en el editor de la UI (no requiere Windows).
- `pydirectinput` se importa perezosamente para que el módulo cargue en Linux/macOS (dev/test).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

# SEGURIDAD: la tecla Windows/Super/Cmd fue REMOVIDA a propósito. No tiene uso
# legítimo en binds de Star Citizen (minimiza el juego) y era el vector principal
# de RCE: un perfil malicioso compartido podía declarar `win+r` → escribir un
# comando → `enter` y ejecutar código arbitrario con los privilegios de admin
# con los que corre Origin (por Easy Anti-Cheat). Ver `_DANGEROUS_COMBOS` abajo
# para el resto de los atajos de sistema bloqueados.
MODIFIERS = ("ctrl", "shift", "alt")
MODIFIER_SET = set(MODIFIERS)
MODIFIER_ORDER = {m: i for i, m in enumerate(MODIFIERS)}

# Aliases comunes que el usuario puede escribir.
KEY_ALIASES = {
    "esc": "escape",
    "return": "enter",
    "ins": "insert",
    "del": "delete",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "control": "ctrl",
    "option": "alt",
}

# Combos de sistema operativo bloqueados por seguridad, representados como
# (frozenset de modificadores, tecla final normalizada). Aunque removimos `win`,
# quedan atajos que abren UI del SO y que un perfil malicioso no debe poder
# disparar en una app que corre como administrador.
_DANGEROUS_COMBOS: set[tuple[frozenset[str], str]] = {
    (frozenset({"ctrl", "shift"}), "escape"),   # Administrador de tareas
    (frozenset({"ctrl", "alt"}), "delete"),     # SAS (no inyectable, pero lo bloqueamos igual)
}

_LETTERS = {chr(c) for c in range(ord("a"), ord("z") + 1)}
_DIGITS = {chr(c) for c in range(ord("0"), ord("9") + 1)}
_FKEYS = {f"f{i}" for i in range(1, 25)}
_SPECIAL_KEYS = {
    "enter", "escape", "tab", "space", "backspace", "delete", "insert",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "capslock", "numlock", "scrolllock", "printscreen", "pause",
    "minus", "equal", "comma", "period", "slash", "backslash",
    "semicolon", "apostrophe", "leftbracket", "rightbracket",
}
VALID_KEYS = _LETTERS | _DIGITS | _FKEYS | _SPECIAL_KEYS | MODIFIER_SET


class KeyError_(ValueError):
    """Error parseando o validando una combinación de teclas."""


def _normalize_token(tok: str) -> str:
    t = tok.strip().lower()
    return KEY_ALIASES.get(t, t)


def parse_combo(combo: str) -> tuple[list[str], str]:
    """`"alt+shift+n"` → (`["shift","alt"]` por MODIFIER_ORDER, `"n"`)."""
    parts = [_normalize_token(p) for p in combo.split("+") if p.strip()]
    if not parts:
        raise KeyError_(f"combo vacío: '{combo}'")
    mods: list[str] = []
    for p in parts[:-1]:
        if p not in MODIFIER_SET:
            raise KeyError_(
                f"'{p}' no es un modificador válido en '{combo}' (usar ctrl/shift/alt/win)"
            )
        if p in mods:
            raise KeyError_(f"modificador duplicado '{p}' en '{combo}'")
        mods.append(p)
    mods.sort(key=lambda m: MODIFIER_ORDER[m])
    key = parts[-1]
    if key not in VALID_KEYS:
        raise KeyError_(f"tecla '{key}' no soportada en '{combo}'")
    if key in MODIFIER_SET and mods:
        # 'ctrl+shift' / 'alt+ctrl' sin tecla final → inválido.
        raise KeyError_(
            f"'{combo}' es solo modificadores; agregá una tecla final (ej. ctrl+shift+a)"
        )
    # SEGURIDAD: rechazar atajos de sistema (defense-in-depth vs perfiles maliciosos).
    if (frozenset(mods), key) in _DANGEROUS_COMBOS:
        raise KeyError_(
            f"'{combo}' es un atajo de sistema bloqueado por seguridad"
        )
    return mods, key


def validate(combo: str) -> str | None:
    """Devuelve None si el combo es válido, o un mensaje de error si no."""
    try:
        parse_combo(combo)
        return None
    except KeyError_ as e:
        return str(e)


def validate_all(combos: Iterable[str]) -> list[str]:
    """Lista de errores (vacía si todo OK). Útil para validar bulk antes de save."""
    return [err for combo in combos if (err := validate(combo)) is not None]


# ============================================================================
# Ejecución
# ============================================================================


def _get_pdi() -> Any:
    """Lazy import. Devuelve None si pydirectinput no está instalado (no-Windows)."""
    try:
        import pydirectinput  # type: ignore[import-untyped]

        return pydirectinput
    except ImportError:
        return None


def execute(combos: list[str], inter_key_delay_ms: int = 30, dry_run: bool = False) -> None:
    """Envía una secuencia de combos. En dry_run solo loguea.

    inter_key_delay_ms aplica ENTRE combos sucesivos. La tecla final de cada combo
    se manda con `press()` (keydown+keyup atómico). Los modificadores se mantienen
    presionados durante el press y se sueltan en orden inverso.
    """
    if not combos:
        return
    parsed = [parse_combo(c) for c in combos]
    if dry_run:
        logger.info("dry_run keys=%s", combos)
        return
    pdi = _get_pdi()
    if pdi is None:
        logger.warning("pydirectinput no disponible — saltando envío de teclas (keys=%s)", combos)
        return
    for i, (mods, key) in enumerate(parsed):
        if i > 0 and inter_key_delay_ms > 0:
            time.sleep(inter_key_delay_ms / 1000.0)
        for m in mods:
            pdi.keyDown(m)
        try:
            pdi.press(key)
        finally:
            for m in reversed(mods):
                pdi.keyUp(m)


def execute_held(combo: str, hold_ms: int, dry_run: bool = False) -> None:
    """Mantiene `combo` presionado durante `hold_ms` antes de soltar.

    Útil para steps tipo `{key: "b", hold_ms: 500}` (ej. spool quantum drive).
    """
    mods, key = parse_combo(combo)
    if dry_run:
        logger.info("dry_run held key=%s hold_ms=%d", combo, hold_ms)
        return
    pdi = _get_pdi()
    if pdi is None:
        logger.warning("pydirectinput no disponible — saltando held key=%s", combo)
        return
    for m in mods:
        pdi.keyDown(m)
    pdi.keyDown(key)
    try:
        time.sleep(max(0, hold_ms) / 1000.0)
    finally:
        pdi.keyUp(key)
        for m in reversed(mods):
            pdi.keyUp(m)
