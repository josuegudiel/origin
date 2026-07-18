"""HOTAS PTT via la librería `inputs` (cross-platform, pure Python).

Patrón: un thread por dispositivo (gp.read() es bloqueante). Cada thread forwarda
press/release del botón bindeado a callbacks compartidos. Si el device desaparece,
el thread duerme 5 s y reintenta.

UI: en vez de un dropdown de nombres de botones adivinados, ofrecemos
`capture_next_press(timeout)` — el usuario aprieta el botón que quiere bindear
y la app guarda el id.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _try_import_inputs() -> Any | None:
    try:
        import inputs  # type: ignore[import-untyped]

        return inputs
    except Exception:
        return None


class HotasListener:
    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        poll_hz: int = 60,
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._poll_hz = poll_hz
        self._binding: tuple[int, str] | None = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._capture_event: threading.Event | None = None
        self._captured: str | None = None

    @property
    def binding(self) -> str | None:
        if self._binding is None:
            return None
        return f"{self._binding[0]}:{self._binding[1]}"

    def set_binding(self, binding: str | None) -> None:
        if binding is None or not binding.strip():
            self._binding = None
            return
        try:
            idx, btn = binding.split(":", 1)
            self._binding = (int(idx), btn.strip())
        except (ValueError, KeyError):
            logger.warning("hotas_invalid_binding value=%r", binding)
            self._binding = None

    @staticmethod
    def enumerate_devices() -> list[dict[str, Any]]:
        inp = _try_import_inputs()
        if inp is None:
            return []
        try:
            return [
                {"index": i, "name": str(gp.name)}
                for i, gp in enumerate(inp.devices.gamepads)
            ]
        except Exception:
            logger.exception("hotas_enumerate_failed")
            return []

    # ---------------------------------------------------------------- threads

    def start(self) -> None:
        if self._threads:
            return
        inp = _try_import_inputs()
        if inp is None:
            logger.info("hotas_inputs_unavailable")
            return
        try:
            gamepads = list(inp.devices.gamepads)
        except Exception:
            logger.exception("hotas_devices_query_failed")
            return
        for i, gp in enumerate(gamepads):
            t = threading.Thread(
                target=self._device_loop, args=(i, gp), daemon=True, name=f"hotas-{i}"
            )
            t.start()
            self._threads.append(t)
        logger.info("hotas_started devices=%d", len(self._threads))

    def stop(self) -> None:
        self._stop.set()
        # Threads son daemon — mueren con el proceso. gp.read() bloquea hasta evento;
        # forzar shutdown limpio requeriría señales de SO no portables. Aceptable.
        self._threads.clear()

    def _device_loop(self, idx: int, gp: Any) -> None:
        period = 1.0 / max(1, self._poll_hz)
        consecutive_errors = 0
        while not self._stop.is_set():
            try:
                events = gp.read()
            except Exception:
                consecutive_errors += 1
                if consecutive_errors == 1:
                    logger.warning("hotas_unplugged device=%d", idx)
                time.sleep(5.0)
                continue
            if consecutive_errors > 0:
                logger.info("hotas_reconnected device=%d", idx)
            consecutive_errors = 0
            for ev in events:
                if getattr(ev, "ev_type", None) != "Key":
                    continue
                code = getattr(ev, "code", None)
                state = getattr(ev, "state", None)
                if code is None or state is None:
                    continue
                # capture mode
                if self._capture_event is not None and state == 1:
                    self._captured = f"{idx}:{code}"
                    self._capture_event.set()
                    continue
                # binding match
                if self._binding is None:
                    continue
                if self._binding != (idx, code):
                    continue
                try:
                    if state == 1:
                        self._on_press()
                    elif state == 0:
                        self._on_release()
                except Exception:
                    logger.exception("hotas_callback_failed")
            time.sleep(period)

    # ---------------------------------------------------------------- capture

    def capture_next_press(self, timeout_s: float = 5.0) -> str | None:
        """Bloquea hasta el próximo press de cualquier device (o timeout). Devuelve
        "<idx>:<button_name>" o None si timeout."""
        if not self._threads:
            return None
        self._captured = None
        self._capture_event = threading.Event()
        try:
            if self._capture_event.wait(timeout_s):
                return self._captured
            return None
        finally:
            self._capture_event = None
