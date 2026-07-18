"""Tests del EventBus."""
from __future__ import annotations

import threading

from origin.engine.events import EventBus, EventType


def test_subscribe_and_emit():
    bus = EventBus()
    received: list[dict] = []
    bus.subscribe(EventType.PROFILE_CHANGED, lambda p: received.append(p))
    bus.emit(EventType.PROFILE_CHANGED, {"profile_id": "flight"})
    assert received == [{"profile_id": "flight"}]


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    received: list[dict] = []
    unsub = bus.subscribe(EventType.PROFILE_CHANGED, lambda p: received.append(p))
    bus.emit(EventType.PROFILE_CHANGED, {"profile_id": "a"})
    unsub()
    bus.emit(EventType.PROFILE_CHANGED, {"profile_id": "b"})
    assert received == [{"profile_id": "a"}]


def test_one_broken_subscriber_does_not_kill_others():
    bus = EventBus()
    received: list[dict] = []

    def boom(_p):
        raise RuntimeError("nope")

    bus.subscribe(EventType.PROFILE_CHANGED, boom)
    bus.subscribe(EventType.PROFILE_CHANGED, lambda p: received.append(p))
    bus.emit(EventType.PROFILE_CHANGED, {"profile_id": "x"})
    assert received == [{"profile_id": "x"}]


def test_concurrent_emits_thread_safe():
    bus = EventBus()
    received: list[dict] = []
    lock = threading.Lock()

    def listener(p):
        with lock:
            received.append(p)

    bus.subscribe(EventType.LOG, listener)

    def emit_n(n):
        for i in range(n):
            bus.emit(EventType.LOG, {"i": i})

    threads = [threading.Thread(target=emit_n, args=(50,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(received) == 200
