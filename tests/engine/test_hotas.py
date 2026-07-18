"""Tests del HotasListener — mockea sys.modules['inputs']."""
from __future__ import annotations

import sys
import time
import types
from unittest.mock import MagicMock

import pytest


class _FakeEvent:
    def __init__(self, ev_type: str, code: str, state: int) -> None:
        self.ev_type = ev_type
        self.code = code
        self.state = state


class _FakeGamepad:
    def __init__(self, name: str = "T.16000M") -> None:
        self.name = name
        self._queue: list[list[_FakeEvent]] = []

    def push(self, events: list[_FakeEvent]) -> None:
        self._queue.append(events)

    def read(self) -> list[_FakeEvent]:
        # Bloqueante: dormimos hasta que haya algo en queue.
        for _ in range(50):
            if self._queue:
                return self._queue.pop(0)
            time.sleep(0.02)
        # Sin más eventos — simulamos unplug temporal.
        raise RuntimeError("no_events_in_test")


@pytest.fixture
def fake_inputs(monkeypatch):
    fake_module = types.ModuleType("inputs")
    fake_module.devices = MagicMock()
    fake_module.devices.gamepads = []
    monkeypatch.setitem(sys.modules, "inputs", fake_module)
    return fake_module


def test_enumerate_devices_empty_when_no_gamepads(fake_inputs):
    from origin.engine.hotas import HotasListener

    assert HotasListener.enumerate_devices() == []


def test_enumerate_devices_lists_gamepads(fake_inputs):
    gp1 = _FakeGamepad("T.16000M")
    gp2 = _FakeGamepad("Warthog Throttle")
    fake_inputs.devices.gamepads = [gp1, gp2]
    from origin.engine.hotas import HotasListener

    devs = HotasListener.enumerate_devices()
    assert [d["name"] for d in devs] == ["T.16000M", "Warthog Throttle"]


def test_button_press_fires_callback(fake_inputs):
    from origin.engine.hotas import HotasListener

    gp = _FakeGamepad("T.16000M")
    fake_inputs.devices.gamepads = [gp]

    presses = []
    releases = []
    listener = HotasListener(
        on_press=lambda: presses.append(1),
        on_release=lambda: releases.append(1),
        poll_hz=120,
    )
    listener.set_binding("0:BTN_THUMB")
    listener.start()
    gp.push([_FakeEvent("Key", "BTN_THUMB", 1)])
    gp.push([_FakeEvent("Key", "BTN_THUMB", 0)])
    time.sleep(0.5)
    listener.stop()
    assert presses and releases


def test_wrong_button_no_callback(fake_inputs):
    from origin.engine.hotas import HotasListener

    gp = _FakeGamepad("X")
    fake_inputs.devices.gamepads = [gp]
    presses = []
    listener = HotasListener(
        on_press=lambda: presses.append(1),
        on_release=lambda: None,
        poll_hz=120,
    )
    listener.set_binding("0:BTN_THUMB")
    listener.start()
    gp.push([_FakeEvent("Key", "BTN_OTHER", 1)])
    time.sleep(0.3)
    listener.stop()
    assert presses == []


def test_set_binding_none_disables(fake_inputs):
    from origin.engine.hotas import HotasListener

    listener = HotasListener(on_press=lambda: None, on_release=lambda: None)
    listener.set_binding("0:BTN_THUMB")
    assert listener.binding == "0:BTN_THUMB"
    listener.set_binding(None)
    assert listener.binding is None
