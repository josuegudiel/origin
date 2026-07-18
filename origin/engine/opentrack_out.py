"""Salida hacia OpenTrack por su protocolo UDP.

OpenTrack (y su ecosistema freetrack) acepta datagramas UDP de 6 doubles
little-endian: (yaw, pitch, roll, x, y, z) = 48 bytes, por default al puerto
4242. OpenTrack los recibe con el input "UDP over network" y los reenvía al
juego (TrackIR/freetrack), dando head-look 6DoF en Star Citizen y 200+ juegos.

Este módulo es puro y testeable: no depende de webcam ni de Qt.
"""
from __future__ import annotations

import logging
import socket
import struct

logger = logging.getLogger(__name__)

# 6 doubles little-endian. `<` fija el byte-order (OpenTrack lee nativo x86 LE).
_PACKET = struct.Struct("<6d")
PACKET_SIZE = _PACKET.size  # 48


def encode_pose(
    yaw: float, pitch: float, roll: float, x: float, y: float, z: float
) -> bytes:
    """Codifica una pose 6DoF al datagrama de 48 bytes de OpenTrack."""
    return _PACKET.pack(yaw, pitch, roll, x, y, z)


class OpenTrackSender:
    """Envía poses 6DoF por UDP a OpenTrack. Fire-and-forget (UDP sin ack)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4242) -> None:
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None

    def open(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info("opentrack_sender_open host=%s port=%d", self._host, self._port)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def update_target(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def send(
        self, yaw: float, pitch: float, roll: float, x: float, y: float, z: float
    ) -> bool:
        """Envía una pose. Devuelve True si se mandó, False si falló (no raisa —
        un error de red no debe tumbar el loop de tracking)."""
        if self._sock is None:
            self.open()
        assert self._sock is not None
        try:
            self._sock.sendto(
                encode_pose(yaw, pitch, roll, x, y, z), (self._host, self._port)
            )
            return True
        except OSError as e:
            logger.debug("opentrack_send_failed: %s", e)
            return False
