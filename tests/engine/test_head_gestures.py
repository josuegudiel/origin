"""Tests del detector de gestos de cabeza."""
from __future__ import annotations

from origin.engine.head_gestures import GestureDetector
from origin.engine.headtrack import HeadPose


def _run(detector: GestureDetector, seq: list[tuple[float, HeadPose]]) -> list[str]:
    out = []
    for t, pose in seq:
        g = detector.feed(pose, t)
        if g:
            out.append(g)
    return out


def test_nod_detected():
    d = GestureDetector()
    seq = [(0.1, HeadPose(pitch=-15)), (0.2, HeadPose(pitch=15)), (0.3, HeadPose(pitch=-15))]
    assert "nod" in _run(d, seq)


def test_shake_detected():
    d = GestureDetector()
    seq = [(0.1, HeadPose(yaw=-20)), (0.2, HeadPose(yaw=20)), (0.3, HeadPose(yaw=-20))]
    assert "shake" in _run(d, seq)


def test_tilt_right_detected():
    d = GestureDetector()
    assert d.feed(HeadPose(roll=25), 1.0) == "tilt_right"


def test_tilt_left_detected():
    d = GestureDetector()
    assert d.feed(HeadPose(roll=-25), 1.0) == "tilt_left"


def test_lean_in_out_detected():
    assert GestureDetector().feed(HeadPose(z=-10), 1.0) == "lean_in"
    assert GestureDetector().feed(HeadPose(z=10), 1.0) == "lean_out"


def test_cooldown_prevents_repeat_fire():
    d = GestureDetector()
    assert d.feed(HeadPose(roll=25), 1.0) == "tilt_right"
    assert d.feed(HeadPose(roll=25), 1.2) is None   # dentro del cooldown 1.0s
    assert d.feed(HeadPose(roll=25), 2.5) == "tilt_right"  # cooldown pasó


def test_still_head_no_gestures():
    d = GestureDetector()
    fires = [d.feed(HeadPose(), i * 0.1) for i in range(6)]
    assert not any(fires)


def test_small_movements_below_threshold_ignored():
    d = GestureDetector()
    # roll de 5° (< umbral 18) no dispara tilt
    assert d.feed(HeadPose(roll=5), 1.0) is None


def test_reset_clears_state():
    d = GestureDetector()
    d.feed(HeadPose(roll=25), 1.0)
    d.reset()
    # tras reset, el cooldown se limpia → vuelve a poder disparar
    assert d.feed(HeadPose(roll=25), 1.1) == "tilt_right"
