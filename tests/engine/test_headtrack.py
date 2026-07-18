"""Tests del head tracking: matemática de pose + tracker con backend mock."""
from __future__ import annotations

import time

from origin.engine.config import HeadAxis, HeadTrackSettings
from origin.engine.events import EventBus, EventType
from origin.engine.headtrack import (
    HeadPose,
    HeadTracker,
    MockBackend,
    apply_axis,
    process_pose,
    smooth_pose,
)


# ---------------------------------------------------------------- apply_axis

def test_apply_axis_calibration():
    # raw 30, center 10 → 20
    assert apply_axis(30, 10, HeadAxis()) == 20.0


def test_apply_axis_deadzone_inside_is_zero():
    assert apply_axis(12, 10, HeadAxis(deadzone=5.0)) == 0.0


def test_apply_axis_deadzone_soft_subtract():
    # v=10, dz=5 → 5 (descuento suave)
    assert apply_axis(20, 10, HeadAxis(deadzone=5.0)) == 5.0


def test_apply_axis_sensitivity():
    assert apply_axis(20, 10, HeadAxis(sensitivity=2.0)) == 20.0


def test_apply_axis_invert():
    assert apply_axis(20, 10, HeadAxis(invert=True)) == -10.0


def test_process_pose_all_axes():
    raw = HeadPose(yaw=30, pitch=20, roll=10, x=5, y=4, z=3)
    center = HeadPose(yaw=10, pitch=0, roll=0, x=0, y=0, z=0)
    cfg = HeadTrackSettings(yaw=HeadAxis(invert=True))
    out = process_pose(raw, center, cfg)
    assert out.yaw == -20.0  # (30-10) inverted
    assert out.pitch == 20.0


# ---------------------------------------------------------------- smoothing

def test_smooth_pose_ema():
    p = smooth_pose(HeadPose(yaw=0), HeadPose(yaw=10), 0.5)
    assert p.yaw == 5.0


def test_smooth_pose_alpha_zero_passthrough():
    assert smooth_pose(HeadPose(yaw=0), HeadPose(yaw=10), 0.0).yaw == 10.0


# ---------------------------------------------------------------- MockBackend

def test_mock_backend_cycles_poses():
    b = MockBackend([HeadPose(yaw=1), HeadPose(yaw=2)])
    b.open(0)
    assert b.read_pose().yaw == 1
    assert b.read_pose().yaw == 2
    assert b.read_pose().yaw == 1  # cicla


# ---------------------------------------------------------------- HeadTracker

def test_tracker_emits_pose_and_state_events():
    bus = EventBus()
    poses, states = [], []
    bus.subscribe(EventType.HEAD_POSE, lambda p: poses.append(p))
    bus.subscribe(EventType.HEAD_TRACK_STATE, lambda p: states.append(p["state"]))
    cfg = HeadTrackSettings(backend="mock", fps_target=120, smoothing=0.0)
    ht = HeadTracker(cfg, bus, backend=MockBackend([HeadPose(yaw=30)]))
    ht.start()
    time.sleep(0.2)
    ht.stop()
    assert len(poses) > 0
    assert "running" in states and "stopped" in states


def test_tracker_calibration_zeroes_center():
    bus = EventBus()
    out = []
    bus.subscribe(EventType.HEAD_POSE, lambda p: out.append(p))
    cfg = HeadTrackSettings(backend="mock", fps_target=120, smoothing=0.0)
    ht = HeadTracker(cfg, bus, backend=MockBackend([HeadPose(yaw=45)]))
    ht.calibrate()  # el primer raw pose (yaw=45) se vuelve el centro
    ht.start()
    time.sleep(0.2)
    ht.stop()
    # tras calibrar en yaw=45, la salida debe rondar 0 (raw - center = 0)
    assert out and abs(out[-1]["yaw"]) < 1.0


def test_tracker_on_pose_callback_called():
    bus = EventBus()
    calls = []
    cfg = HeadTrackSettings(backend="mock", fps_target=120)
    ht = HeadTracker(cfg, bus, on_pose=lambda p: calls.append(p), backend=MockBackend([HeadPose()]))
    ht.start()
    time.sleep(0.15)
    ht.stop()
    assert len(calls) > 0
