"""Smoke test end-to-end del head tracking (clon Beam Eye Tracker).

Replica el cableado real de `Orchestrator._start_head_tracker` /
`_on_head_pose` pero sin Qt ni webcam: MockBackend scripteado → HeadTracker
(worker thread real) → on_pose → OpenTrackSender → socket UDP real en
loopback → datagrama de 48 bytes decodificado, y el mismo stream alimenta el
GestureDetector. Verifica que la cadena completa corre, no solo las piezas.
"""
from __future__ import annotations

import socket
import struct
import time

from origin.engine.config import HeadTrackSettings
from origin.engine.events import EventBus, EventType
from origin.engine.head_gestures import GestureDetector
from origin.engine.headtrack import HeadPose, HeadTracker, MockBackend
from origin.engine.opentrack_out import PACKET_SIZE, OpenTrackSender

_RECV_TIMEOUT_S = 3.0


def _make_settings(**overrides) -> HeadTrackSettings:
    base = {"enabled": True, "backend": "mock", "fps_target": 120, "smoothing": 0.0}
    base.update(overrides)
    return HeadTrackSettings.model_validate(base)


def _udp_receiver() -> tuple[socket.socket, int]:
    """Socket UDP real en loopback, puerto efímero (como OpenTrack escuchando)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(_RECV_TIMEOUT_S)
    return sock, sock.getsockname()[1]


def test_e2e_tracker_to_opentrack_udp():
    """Pose scripteada atraviesa tracker → sender → UDP y llega intacta."""
    recv, port = _udp_receiver()
    sender = OpenTrackSender("127.0.0.1", port)
    bus = EventBus()
    cfg = _make_settings()
    ht = HeadTracker(
        cfg, bus,
        on_pose=lambda p: sender.send(*p.as_tuple()),
        backend=MockBackend([HeadPose(yaw=30.0, pitch=-10.0, roll=5.0, z=2.0)]),
    )
    try:
        ht.start()
        data, addr = recv.recvfrom(64)
    finally:
        ht.stop()
        sender.close()
        recv.close()
    assert addr[0] == "127.0.0.1"
    assert len(data) == PACKET_SIZE == 48
    yaw, pitch, roll, x, y, z = struct.unpack("<6d", data)
    assert (yaw, pitch, roll, x, y, z) == (30.0, -10.0, 5.0, 0.0, 0.0, 2.0)


def test_e2e_axis_config_applied_before_udp():
    """Sensibilidad e invert de la config afectan lo que sale por el socket."""
    recv, port = _udp_receiver()
    sender = OpenTrackSender("127.0.0.1", port)
    bus = EventBus()
    cfg = _make_settings(yaw={"sensitivity": 2.0, "invert": True})
    ht = HeadTracker(
        cfg, bus,
        on_pose=lambda p: sender.send(*p.as_tuple()),
        backend=MockBackend([HeadPose(yaw=10.0)]),
    )
    try:
        ht.start()
        data, _ = recv.recvfrom(64)
    finally:
        ht.stop()
        sender.close()
        recv.close()
    yaw = struct.unpack("<6d", data)[0]
    assert yaw == -20.0  # 10 * 2.0, invertido


def test_e2e_gesture_nod_from_pose_stream():
    """El stream del tracker (thread real) dispara 'nod' en el detector."""
    bus = EventBus()
    detector = GestureDetector()
    fired: list[str] = []

    def on_pose(pose: HeadPose) -> None:
        g = detector.feed(pose, time.monotonic())
        if g is not None:
            fired.append(g)

    # Vaivén de pitch ±15° (umbral nod: 12°) — el mock cicla la secuencia.
    ht = HeadTracker(
        _make_settings(), bus, on_pose=on_pose,
        backend=MockBackend([HeadPose(pitch=15.0), HeadPose(pitch=-15.0)]),
    )
    try:
        ht.start()
        deadline = time.monotonic() + _RECV_TIMEOUT_S
        while not fired and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        ht.stop()
    assert fired and fired[0] == "nod"


def test_e2e_calibrate_then_stream_zeroed():
    """calibrate() marca el centro: la salida posterior queda en ~0."""
    bus = EventBus()
    poses: list[dict] = []
    bus.subscribe(EventType.HEAD_POSE, poses.append)
    ht = HeadTracker(
        _make_settings(), bus,
        backend=MockBackend([HeadPose(yaw=45.0, pitch=8.0)]),
    )
    try:
        ht.start()
        deadline = time.monotonic() + _RECV_TIMEOUT_S
        while not poses and time.monotonic() < deadline:
            time.sleep(0.01)
        assert poses and poses[-1]["yaw"] == 45.0
        ht.calibrate()
        n = len(poses)
        while len(poses) < n + 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        ht.stop()
    assert poses[-1]["yaw"] == 0.0 and poses[-1]["pitch"] == 0.0


def test_e2e_stop_terminates_worker_and_socket():
    """stop() apaga el thread y cierra el backend sin colgarse (shutdown limpio)."""
    bus = EventBus()
    states: list[str] = []
    bus.subscribe(EventType.HEAD_TRACK_STATE, lambda p: states.append(p["state"]))
    ht = HeadTracker(_make_settings(), bus, backend=MockBackend([HeadPose()]))
    ht.start()
    t0 = time.monotonic()
    deadline = t0 + _RECV_TIMEOUT_S
    while "running" not in states and time.monotonic() < deadline:
        time.sleep(0.01)
    ht.stop()
    assert time.monotonic() - t0 < _RECV_TIMEOUT_S + 2.5  # join con timeout 2s
    assert states[0] == "starting" and "running" in states and states[-1] == "stopped"
    assert ht._thread is None
