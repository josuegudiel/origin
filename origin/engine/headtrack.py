"""Head tracking por webcam (núcleo tipo Beam Eye Tracker).

Estima la pose de la cabeza (yaw/pitch/roll + x/y/z) desde una webcam común y
la publica por `EventBus` (`HEAD_POSE`) + la manda a callbacks de salida
(OpenTrack UDP, detector de gestos).

Arquitectura:
- La matemática de pose (calibración, deadzone, sensibilidad, invert, EMA) son
  funciones PURAS testeables sin webcam.
- El backend de estimación es intercambiable: `mediapipe` (real, lazy-import de
  cv2 + mediapipe, solo Windows/hardware) o `mock` (poses scripteadas para
  dev/tests). El módulo importa en Linux sin cv2/mediapipe.
- `HeadTracker` corre un worker thread a `fps_target`, no bloquea la UI.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .config import HeadAxis, HeadTrackSettings
from .events import EventBus, EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeadPose:
    """Pose 6DoF. Rotaciones en grados, traslaciones en unidades normalizadas."""

    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.yaw, self.pitch, self.roll, self.x, self.y, self.z)


# ============================================================================
# Matemática de pose (pura)
# ============================================================================


def apply_axis(raw: float, center: float, cfg: HeadAxis) -> float:
    """Aplica calibración (resta center), deadzone, sensibilidad e invert a un eje."""
    v = raw - center
    if cfg.deadzone > 0.0:
        if abs(v) <= cfg.deadzone:
            v = 0.0
        else:
            # Deadzone suave: descuenta la zona muerta para que no haya salto.
            v = v - cfg.deadzone if v > 0 else v + cfg.deadzone
    v *= cfg.sensitivity
    if cfg.invert:
        v = -v
    return v


def process_pose(raw: HeadPose, center: HeadPose, cfg: HeadTrackSettings) -> HeadPose:
    """Convierte una pose cruda en la pose final aplicando la config por eje."""
    return HeadPose(
        yaw=apply_axis(raw.yaw, center.yaw, cfg.yaw),
        pitch=apply_axis(raw.pitch, center.pitch, cfg.pitch),
        roll=apply_axis(raw.roll, center.roll, cfg.roll),
        x=apply_axis(raw.x, center.x, cfg.pos_x),
        y=apply_axis(raw.y, center.y, cfg.pos_y),
        z=apply_axis(raw.z, center.z, cfg.pos_z),
    )


def smooth_pose(prev: HeadPose, new: HeadPose, alpha: float) -> HeadPose:
    """EMA: alpha alto = más suave/lento. alpha=0 → sin suavizado."""
    if alpha <= 0.0:
        return new
    a = alpha
    b = 1.0 - alpha
    return HeadPose(
        yaw=a * prev.yaw + b * new.yaw,
        pitch=a * prev.pitch + b * new.pitch,
        roll=a * prev.roll + b * new.roll,
        x=a * prev.x + b * new.x,
        y=a * prev.y + b * new.y,
        z=a * prev.z + b * new.z,
    )


# ============================================================================
# Backends de estimación
# ============================================================================


class PoseBackend(Protocol):
    def open(self, camera_index: int) -> None: ...
    def read_pose(self) -> HeadPose | None: ...  # None si no hay cara
    def close(self) -> None: ...


class MockBackend:
    """Backend sin webcam: reproduce una lista de poses (para dev/tests)."""

    def __init__(self, poses: list[HeadPose] | None = None) -> None:
        self._poses = poses or [HeadPose()]
        self._i = 0

    def open(self, camera_index: int) -> None:
        self._i = 0

    def read_pose(self) -> HeadPose | None:
        if not self._poses:
            return None
        p = self._poses[self._i % len(self._poses)]
        self._i += 1
        return p

    def close(self) -> None:
        pass


class MediaPipeBackend:
    """Backend real: cv2.VideoCapture + MediaPipe FaceMesh + solvePnP.

    Todo el import pesado (cv2, mediapipe, numpy) es perezoso — el módulo carga
    en Linux sin estas deps; este backend solo se instancia en Windows/hardware.
    """

    # Puntos 3D canónicos de una cara (mm aprox) alineados con los landmarks de
    # MediaPipe que usamos para solvePnP: nariz, mentón, ojos, boca.
    _MODEL_POINTS = (
        (0.0, 0.0, 0.0),        # nose tip (landmark 1)
        (0.0, -63.6, -12.5),    # chin (152)
        (-43.3, 32.7, -26.0),   # left eye outer (33)
        (43.3, 32.7, -26.0),    # right eye outer (263)
        (-28.9, -28.9, -24.1),  # left mouth (61)
        (28.9, -28.9, -24.1),   # right mouth (291)
    )
    _LANDMARK_IDS = (1, 152, 33, 263, 61, 291)

    def __init__(self) -> None:
        self._cap: Any = None
        self._mesh: Any = None
        self._np: Any = None
        self._cv2: Any = None

    def open(self, camera_index: int) -> None:
        import cv2  # noqa: PLC0415
        import mediapipe as mp  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        self._cv2 = cv2
        self._np = np
        self._cap = cv2.VideoCapture(camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"no se pudo abrir la cámara {camera_index}")
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1, refine_landmarks=False,
            min_detection_confidence=0.5, min_tracking_confidence=0.5,
        )

    def read_pose(self) -> HeadPose | None:
        if self._cap is None or self._mesh is None:
            return None
        ok, frame = self._cap.read()
        if not ok:
            return None
        h, w = frame.shape[:2]
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        res = self._mesh.process(rgb)
        if not res.multi_face_landmarks:
            return None
        lms = res.multi_face_landmarks[0].landmark
        np = self._np
        image_points = np.array(
            [(lms[i].x * w, lms[i].y * h) for i in self._LANDMARK_IDS], dtype=np.float64
        )
        model_points = np.array(self._MODEL_POINTS, dtype=np.float64)
        focal = float(w)
        cam_matrix = np.array(
            [[focal, 0, w / 2], [0, focal, h / 2], [0, 0, 1]], dtype=np.float64
        )
        dist = np.zeros((4, 1))
        ok2, rvec, tvec = self._cv2.solvePnP(
            model_points, image_points, cam_matrix, dist,
            flags=self._cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok2:
            return None
        rmat, _ = self._cv2.Rodrigues(rvec)
        sy = float((rmat[0, 0] ** 2 + rmat[1, 0] ** 2) ** 0.5)
        import math  # noqa: PLC0415
        pitch = math.degrees(math.atan2(-rmat[2, 0], sy))
        yaw = math.degrees(math.atan2(rmat[1, 0], rmat[0, 0]))
        roll = math.degrees(math.atan2(rmat[2, 1], rmat[2, 2]))
        tx, ty, tz = float(tvec[0]), float(tvec[1]), float(tvec[2])
        # Normalizamos traslación a un rango manejable para OpenTrack.
        return HeadPose(yaw=yaw, pitch=pitch, roll=roll,
                        x=tx / 10.0, y=ty / 10.0, z=(tz - 500.0) / 10.0)

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._mesh is not None:
            try:
                self._mesh.close()
            except Exception:
                pass
            self._mesh = None


def make_backend(name: str) -> PoseBackend:
    if name == "mock":
        return MockBackend()
    return MediaPipeBackend()


# ============================================================================
# HeadTracker
# ============================================================================


class HeadTracker:
    """Worker de head tracking. `on_pose(final_pose)` recibe cada pose procesada."""

    def __init__(
        self,
        settings: HeadTrackSettings,
        bus: EventBus,
        on_pose: Callable[[HeadPose], None] | None = None,
        backend: PoseBackend | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._on_pose = on_pose
        self._backend = backend or make_backend(settings.backend)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._center = HeadPose()
        self._last_raw = HeadPose()
        self._smoothed = HeadPose()
        self._calibrate_next = False

    def update_settings(self, settings: HeadTrackSettings) -> None:
        with self._lock:
            self._settings = settings

    def calibrate(self) -> None:
        """Marca la pose cruda actual como el centro (posición neutral)."""
        self._calibrate_next = True

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="head-track")
        self._thread.start()
        self._bus.emit(EventType.HEAD_TRACK_STATE, {"state": "starting"})

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        try:
            self._backend.close()
        except Exception:
            logger.exception("head_backend_close_failed")
        self._bus.emit(EventType.HEAD_TRACK_STATE, {"state": "stopped"})

    def _loop(self) -> None:
        try:
            self._backend.open(self._settings.camera_index)
        except Exception as e:
            logger.warning("head_backend_open_failed: %s", e)
            self._bus.emit(EventType.HEAD_TRACK_STATE, {"state": "error", "error": str(e)})
            return
        self._bus.emit(EventType.HEAD_TRACK_STATE, {"state": "running"})
        period = 1.0 / max(1, self._settings.fps_target)
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                raw = self._backend.read_pose()
            except Exception:
                logger.exception("head_read_pose_failed")
                raw = None
            if raw is not None:
                self._handle_raw(raw)
            dt = time.monotonic() - t0
            if dt < period:
                self._stop.wait(period - dt)

    def _handle_raw(self, raw: HeadPose) -> None:
        with self._lock:
            settings = self._settings
            if self._calibrate_next:
                self._center = raw
                self._calibrate_next = False
                logger.info("head_calibrated center=%s", raw.as_tuple())
            self._last_raw = raw
            final = process_pose(raw, self._center, settings)
            self._smoothed = smooth_pose(self._smoothed, final, settings.smoothing)
            out = self._smoothed
        self._bus.emit(
            EventType.HEAD_POSE,
            {"yaw": out.yaw, "pitch": out.pitch, "roll": out.roll,
             "x": out.x, "y": out.y, "z": out.z},
        )
        if self._on_pose is not None:
            try:
                self._on_pose(out)
            except Exception:
                logger.exception("head_on_pose_failed")

    @staticmethod
    def list_cameras(max_index: int = 8) -> list[int]:
        """Índices de cámara disponibles. [] si cv2 no está o no hay cámaras."""
        try:
            import cv2  # noqa: PLC0415
        except Exception:
            return []
        found = []
        for i in range(max_index):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                found.append(i)
                cap.release()
        return found
