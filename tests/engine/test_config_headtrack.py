"""Tests del schema de head tracking + seguridad."""
from __future__ import annotations

from pathlib import Path

import pytest

from origin.engine import config as cfgmod


def test_headtrack_defaults():
    s = cfgmod.Settings()
    assert s.headtrack.enabled is False
    assert s.headtrack.camera_index == 0
    assert s.headtrack.backend == "mediapipe"
    assert s.headtrack.opentrack.host == "127.0.0.1"
    assert s.headtrack.opentrack.port == 4242


def test_headtrack_nested_with_settings_preserves_axes():
    cf = cfgmod.CommandsFileV3.model_validate({
        "version": 3, "settings": {"active_profile": "p"},
        "profiles": [{"id": "p", "commands": [{"id": "c", "phrases_es": ["x"], "keys": ["a"]}]}],
    })
    # cambiar solo un campo del headtrack no debe perder los demás
    cf2 = cf.with_settings(headtrack={"enabled": True, "camera_index": 2})
    assert cf2.settings.headtrack.enabled is True
    assert cf2.settings.headtrack.camera_index == 2
    assert cf2.settings.headtrack.opentrack.port == 4242  # default preservado


def test_gesture_binding_valid():
    gb = cfgmod.GestureBinding(gesture="nod", command_id="request_landing")
    assert gb.gesture == "nod" and gb.command_id == "request_landing"


def test_gesture_invalid_name_rejected():
    with pytest.raises(Exception):
        cfgmod.GestureBinding(gesture="wink", command_id="x")


def test_gesture_invalid_command_id_rejected():
    with pytest.raises(Exception):
        cfgmod.GestureBinding(gesture="nod", command_id="../evil")


@pytest.mark.parametrize("host", ["evil.com/../x", "a\\b", "1.2.3.4:5", ""])
def test_opentrack_host_dangerous_rejected(host):
    with pytest.raises(Exception):
        cfgmod.OpenTrackSettings(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "192.168.1.5"])
def test_opentrack_host_legit_accepted(host):
    assert cfgmod.OpenTrackSettings(host=host).host == host


@pytest.mark.parametrize("port", [0, 70000, -1])
def test_opentrack_port_out_of_range_rejected(port):
    with pytest.raises(Exception):
        cfgmod.OpenTrackSettings(port=port)


def test_head_axis_ranges():
    with pytest.raises(Exception):
        cfgmod.HeadAxis(sensitivity=100)   # > 8
    with pytest.raises(Exception):
        cfgmod.HeadAxis(deadzone=90)       # > 45
    assert cfgmod.HeadAxis(sensitivity=3.0, deadzone=10.0).sensitivity == 3.0


def test_headtrack_config_roundtrip_yaml(tmp_path: Path):
    cf = cfgmod.CommandsFileV3.model_validate({
        "version": 3, "settings": {
            "active_profile": "p",
            "headtrack": {
                "enabled": True, "camera_index": 1, "backend": "mock",
                "yaw": {"sensitivity": 2.0, "invert": True},
                "opentrack": {"enabled": True, "host": "127.0.0.1", "port": 4242},
                "gestures": [{"gesture": "nod", "command_id": "c"}],
            },
        },
        "profiles": [{"id": "p", "commands": [{"id": "c", "phrases_es": ["x"], "keys": ["a"]}]}],
    })
    out = tmp_path / "commands.yaml"
    cfgmod.save_atomic(cf, out)
    reloaded = cfgmod.load(out)
    ht = reloaded.settings.headtrack
    assert ht.enabled and ht.camera_index == 1 and ht.yaw.sensitivity == 2.0
    assert ht.yaw.invert is True
    assert len(ht.gestures) == 1 and ht.gestures[0].gesture == "nod"
