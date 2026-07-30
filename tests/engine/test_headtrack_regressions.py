"""Regresiones de la auditoría v0.3.1 del head tracking (clon Beam Eye Tracker).

Cada test acá corresponde a un bug real encontrado auditando el subsistema:
ejes Euler permutados, motor colgado en RUNNING_SCRIPT tras un gesto, gestos
desvirtuados por la sensibilidad del head-look, socket que revivía tras
cerrarse, y reinicio innecesario de la webcam al tocar un slider.
"""
from __future__ import annotations

import math
import time

import pytest

from origin.engine import config as cfgmod
from origin.engine.events import EventBus
from origin.engine.head_gestures import GestureDetector
from origin.engine.headtrack import (
    HeadPose,
    center_pose,
    decode_euler,
    process_pose,
    wrap_deg,
)
from origin.engine.opentrack_out import OpenTrackSender


def _rot(axis: str, deg: float) -> list[list[float]]:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if axis == "y":
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


# ------------------------------------------------- decode Euler (ejes correctos)


@pytest.mark.parametrize(
    ("axis", "idx", "nombre"),
    [("y", 0, "yaw"), ("x", 1, "pitch"), ("z", 2, "roll")],
)
def test_decode_euler_cada_rotacion_sale_por_su_canal(axis, idx, nombre):
    """REGRESIÓN: los tres ejes estaban permutados cíclicamente.

    Girar la cabeza salía por `pitch`, cabecear por `roll` e inclinar por `yaw`:
    el head-look de OpenTrack quedaba cruzado y `nod` se disparaba al negar.
    """
    out = decode_euler(_rot(axis, 20.0))
    assert out[idx] == pytest.approx(20.0, abs=0.5), f"{nombre} no recibió la rotación"
    for j, v in enumerate(out):
        if j != idx:
            assert abs(v) < 0.5, f"la rotación se filtró al canal {j}"


def test_decode_euler_identidad_es_pose_neutra():
    assert decode_euler(_rot("x", 0.0)) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_decode_euler_gimbal_lock_no_explota():
    """Mirando casi de perfil (sy≈0) el decode no debe lanzar."""
    yaw, pitch, roll = decode_euler(_rot("y", 90.0))
    assert abs(yaw) == pytest.approx(90.0, abs=0.5)
    assert math.isfinite(pitch) and math.isfinite(roll)


# ------------------------------------------------------------- wrap de ángulos


def test_wrap_deg_cruce_de_180():
    assert wrap_deg(359.0) == pytest.approx(-1.0)
    assert wrap_deg(-359.0) == pytest.approx(1.0)
    assert wrap_deg(10.0) == pytest.approx(10.0)


def test_process_pose_calibrado_cerca_de_180_no_da_salto():
    """REGRESIÓN: la cara en reposo queda cerca de ±180° en pitch; restar el
    centro sin normalizar convertía un micro-movimiento en ~358°."""
    cfg = cfgmod.HeadTrackSettings()
    out = process_pose(HeadPose(pitch=179.0), HeadPose(pitch=-179.0), cfg)
    assert abs(out.pitch) == pytest.approx(2.0, abs=0.01)


# ------------------------------------ gestos sobre pose centrada SIN escalar


def test_center_pose_ignora_sensibilidad_e_invert():
    assert center_pose(HeadPose(yaw=10.0, z=2.0), HeadPose()) == HeadPose(yaw=10.0, z=2.0)


def test_gestos_no_se_invierten_al_invertir_el_eje():
    """REGRESIÓN: con `roll.invert` (ajuste típico del head-look) los gestos
    tilt_left y tilt_right quedaban intercambiados, porque el detector recibía
    la pose ya escalada e invertida."""
    cfg = cfgmod.HeadTrackSettings.model_validate({"roll": {"invert": True}})
    raw = HeadPose(roll=25.0)          # cabeza inclinada a la derecha
    escalada = process_pose(raw, HeadPose(), cfg)
    centrada = center_pose(raw, HeadPose())

    assert GestureDetector().feed(escalada, 0.0) == "tilt_left"   # lo que pasaba antes
    assert GestureDetector().feed(centrada, 0.0) == "tilt_right"  # lo correcto ahora


def test_gestos_siguen_vivos_con_sensibilidad_cero():
    """REGRESIÓN: `sensitivity=0` es válido y anulaba TODOS los gestos."""
    cfg = cfgmod.HeadTrackSettings.model_validate({"roll": {"sensitivity": 0.0}})
    raw = HeadPose(roll=25.0)
    assert GestureDetector().feed(process_pose(raw, HeadPose(), cfg), 0.0) is None
    assert GestureDetector().feed(center_pose(raw, HeadPose()), 0.0) == "tilt_right"


def test_ventana_de_oscilacion_no_depende_de_los_fps():
    """REGRESIÓN: el historial de 30 muestras recortaba la ventana a 0.25s con
    fps_target=120, así que el mismo cabeceo se detectaba o no según los fps."""
    det = GestureDetector()
    fired = None
    # Cabeceo de 0.8s muestreado a 120 fps (dentro de _OSC_WINDOW_S = 0.9s).
    for i in range(96):
        t = i / 120.0
        pitch = 15.0 if t < 0.4 else -15.0
        fired = det.feed(HeadPose(pitch=pitch), t) or fired
    assert fired == "nod"


# ------------------------------------------------------------ OpenTrackSender


def test_sender_no_revive_despues_de_close():
    """REGRESIÓN: `send()` reabría el socket tras `close()`, filtrando un FD y
    dejando salir poses después del shutdown."""
    s = OpenTrackSender("127.0.0.1", 4242)
    s.open()
    assert s.send(1, 2, 3, 4, 5, 6) is True
    s.close()
    assert s.send(1, 2, 3, 4, 5, 6) is False
    assert s._sock is None
    s.open()  # reapertura explícita: sí permitida
    assert s.send(1, 2, 3, 4, 5, 6) is True
    s.close()


# --------------------------------------------- runtime: estado tras un gesto


@pytest.fixture
def orch_con_gesto(tmp_path, fixtures_dir):
    import shutil

    from origin.engine.runtime import Orchestrator, State

    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    bus = EventBus()
    orch = Orchestrator(tmp_path / "commands.yaml", bus, dry_run=True)
    orch._build_tts()
    orch._build_script_executor()
    orch._cf = orch._cf.with_settings(headtrack={
        "enabled": True, "backend": "mock",
        "gestures": [{"gesture": "nod", "command_id": "request_landing"}],
    })
    orch._settings = orch._cf.settings
    orch._set_state(State.READY)
    return orch, bus


def test_gesto_no_deja_el_motor_colgado_en_running_script(orch_con_gesto):
    """REGRESIÓN CRÍTICA: `_dispatch_command` deja el estado en RUNNING_SCRIPT y
    la ruta de gestos no lo restauraba. Tras UN gesto el motor quedaba ocupado
    para siempre: ignoraba todo PTT y todos los gestos siguientes."""
    from origin.engine.runtime import State

    orch, _bus = orch_con_gesto
    # Cabeceo: cruza +12° y -12° dentro de la ventana → dispara 'nod'.
    orch._on_head_centered(HeadPose(pitch=15.0))
    orch._on_head_centered(HeadPose(pitch=-15.0))
    orch._on_head_centered(HeadPose(pitch=15.0))

    deadline = time.monotonic() + 3.0
    while orch.state != State.READY and time.monotonic() < deadline:
        time.sleep(0.01)
    assert orch.state == State.READY, f"quedó colgado en {orch.state}"


def test_segundo_gesto_sigue_funcionando(orch_con_gesto):
    """Corolario del anterior: el motor acepta gestos repetidos."""
    ejecutados: list[str] = []
    orch, bus = orch_con_gesto
    from origin.engine.events import EventType
    from origin.engine.runtime import State

    bus.subscribe(EventType.COMMAND_EXECUTED, lambda p: ejecutados.append(p["command_id"]))

    for ronda in range(2):
        base = ronda * 10.0  # separa las rondas más allá del cooldown (1s)
        orch._on_head_centered(HeadPose(pitch=15.0))
        orch._gestures._last_fire.clear() if ronda else None
        orch._on_head_centered(HeadPose(pitch=-15.0))
        deadline = time.monotonic() + 3.0
        while orch.state != State.READY and time.monotonic() < deadline:
            time.sleep(0.01)
        del base
    assert len(ejecutados) == 2, f"esperaba 2 ejecuciones, hubo {ejecutados}"


# ------------------------------- apply_settings: no reabrir la cámara de más


def test_cambiar_sensibilidad_no_reinicia_el_tracker(orch_con_gesto, monkeypatch):
    """REGRESIÓN: cualquier cambio del bloque headtrack cerraba y reabría la
    webcam (segundos con cv2) y descartaba la calibración — y la UI persiste en
    cada pulsación de flecha del spinbox."""
    orch, _bus = orch_con_gesto
    reinicios = {"n": 0}
    monkeypatch.setattr(orch, "_stop_head_tracker",
                        lambda: reinicios.__setitem__("n", reinicios["n"] + 1))
    monkeypatch.setattr(orch, "_start_head_tracker", lambda: None)

    class FakeHead:
        def __init__(self):
            self.updates = 0

        def update_settings(self, s):
            self.updates += 1

    fake = FakeHead()
    orch._head = fake

    ht = orch.config.settings.headtrack.model_dump()
    ht["yaw"]["sensitivity"] = 2.5
    orch.set_setting(headtrack=ht)
    assert reinicios["n"] == 0, "no debía reabrir la cámara"
    assert fake.updates == 1, "debía aplicar el cambio en caliente"


def test_cambiar_camara_si_reinicia_el_tracker(orch_con_gesto, monkeypatch):
    orch, _bus = orch_con_gesto
    reinicios = {"n": 0}
    monkeypatch.setattr(orch, "_stop_head_tracker",
                        lambda: reinicios.__setitem__("n", reinicios["n"] + 1))
    monkeypatch.setattr(orch, "_start_head_tracker", lambda: None)
    orch._head = object()

    ht = orch.config.settings.headtrack.model_dump()
    ht["camera_index"] = 2
    orch.set_setting(headtrack=ht)
    assert reinicios["n"] == 1
