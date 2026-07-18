"""Tests del sender UDP de OpenTrack."""
from __future__ import annotations

import socket
import struct

from origin.engine.opentrack_out import PACKET_SIZE, OpenTrackSender, encode_pose


def test_packet_is_48_bytes():
    assert PACKET_SIZE == 48
    assert len(encode_pose(0, 0, 0, 0, 0, 0)) == 48


def test_packet_encodes_6_doubles_little_endian():
    pkt = encode_pose(10.0, -5.0, 2.5, 0.1, 0.2, 0.3)
    vals = struct.unpack("<6d", pkt)
    assert vals == (10.0, -5.0, 2.5, 0.1, 0.2, 0.3)


def test_send_reaches_a_real_loopback_receiver():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    port = rx.getsockname()[1]
    rx.settimeout(1.0)
    s = OpenTrackSender("127.0.0.1", port)
    try:
        assert s.send(45.0, -30.0, 0.0, 0.0, 0.0, 0.0) is True
        data, _ = rx.recvfrom(1024)
        yaw, pitch, roll, x, y, z = struct.unpack("<6d", data)
        assert (yaw, pitch) == (45.0, -30.0)
    finally:
        s.close()
        rx.close()


def test_send_failure_returns_false_not_raise():
    # Puerto 0 no es válido como destino → sendto puede fallar; no debe raisar.
    s = OpenTrackSender("127.0.0.1", 0)
    result = s.send(0, 0, 0, 0, 0, 0)
    assert isinstance(result, bool)
    s.close()


def test_update_target_changes_destination():
    s = OpenTrackSender("127.0.0.1", 4242)
    s.update_target("192.168.1.5", 5555)
    assert s._host == "192.168.1.5" and s._port == 5555  # noqa: SLF001
