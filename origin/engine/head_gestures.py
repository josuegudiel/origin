"""Detector de gestos de cabeza a partir del stream de poses.

Convierte movimientos discretos de la cabeza en eventos de gesto que el runtime
mapea a comandos del perfil (reusando el dispatch + keypress endurecido):

- nod         → cabecear (pitch abajo-arriba en una ventana corta)
- shake       → negar (yaw a un lado y al otro)
- tilt_left/right → inclinar la cabeza (roll sostenido)
- lean_in/out → acercar/alejar la cabeza (z sostenido)

Es puro/testeable: `feed(pose, t)` recibe poses (procesadas) y timestamps y
devuelve el nombre del gesto o None. Sin webcam ni Qt. Cooldown por gesto para
no disparar en ráfaga.
"""
from __future__ import annotations

from collections import deque

from .headtrack import HeadPose

# Umbrales (grados para rotación; unidades normalizadas para z). Elegidos para
# gestos deliberados, no micro-movimientos.
_NOD_PITCH_DEG = 12.0
_SHAKE_YAW_DEG = 15.0
_TILT_ROLL_DEG = 18.0
_LEAN_Z = 6.0
_OSC_WINDOW_S = 0.9      # ventana para nod/shake (oscilación)
_COOLDOWN_S = 1.0        # anti-ráfaga por gesto
_HISTORY = 30


class GestureDetector:
    def __init__(self) -> None:
        self._hist: deque[tuple[float, HeadPose]] = deque(maxlen=_HISTORY)
        self._last_fire: dict[str, float] = {}

    def reset(self) -> None:
        self._hist.clear()
        self._last_fire.clear()

    def _cooled(self, gesture: str, t: float) -> bool:
        return t - self._last_fire.get(gesture, -1e9) >= _COOLDOWN_S

    def _fire(self, gesture: str, t: float) -> str:
        self._last_fire[gesture] = t
        return gesture

    def feed(self, pose: HeadPose, t: float) -> str | None:
        """Alimenta una pose; devuelve el gesto detectado o None."""
        self._hist.append((t, pose))
        window = [(ts, p) for ts, p in self._hist if t - ts <= _OSC_WINDOW_S]

        # --- oscilatorios: nod / shake ---
        if len(window) >= 3:
            pitches = [p.pitch for _, p in window]
            yaws = [p.yaw for _, p in window]
            if self._cooled("nod", t) and _has_swing(pitches, _NOD_PITCH_DEG):
                return self._fire("nod", t)
            if self._cooled("shake", t) and _has_swing(yaws, _SHAKE_YAW_DEG):
                return self._fire("shake", t)

        # --- sostenidos: tilt / lean (borde: cruza el umbral) ---
        if self._cooled("tilt_left", t) and pose.roll <= -_TILT_ROLL_DEG:
            return self._fire("tilt_left", t)
        if self._cooled("tilt_right", t) and pose.roll >= _TILT_ROLL_DEG:
            return self._fire("tilt_right", t)
        if self._cooled("lean_in", t) and pose.z <= -_LEAN_Z:
            return self._fire("lean_in", t)
        if self._cooled("lean_out", t) and pose.z >= _LEAN_Z:
            return self._fire("lean_out", t)
        return None


def _has_swing(values: list[float], threshold: float) -> bool:
    """True si la señal cruza +threshold y -threshold dentro de la ventana
    (un vaivén a ambos lados del centro), característico de nod/shake."""
    return max(values) >= threshold and min(values) <= -threshold
