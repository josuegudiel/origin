"""Tests del ProfileRegistry."""
from __future__ import annotations

from pathlib import Path

from origin.engine import config as cfgmod
from origin.engine.profiles import ProfileRegistry


def test_active_and_set_active(fixtures_dir: Path):
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    reg = ProfileRegistry(cf)
    assert reg.active_id == "flight"
    assert reg.set_active("fps") is True
    assert reg.active_id == "fps"
    assert reg.set_active("nonexistent") is False


def test_matcher_cached_until_switch(fixtures_dir: Path):
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    reg = ProfileRegistry(cf)
    m1 = reg.matcher()
    m2 = reg.matcher()
    assert m1 is m2
    reg.set_active("fps")
    m3 = reg.matcher()
    assert m3 is not m1


def test_cycle_next_wraps_around(fixtures_dir: Path):
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    reg = ProfileRegistry(cf)
    assert reg.cycle_next() == "fps"
    assert reg.cycle_next() == "flight"


def test_replace_config_keeps_active_if_still_present(fixtures_dir: Path):
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    reg = ProfileRegistry(cf)
    reg.set_active("fps")
    new_cf = cf  # mismo set de perfiles
    reg.replace_config(new_cf)
    assert reg.active_id == "fps"


def test_replace_config_falls_back_when_active_disappears(fixtures_dir: Path):
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    reg = ProfileRegistry(cf)
    reg.set_active("fps")
    # nueva config sin 'fps'
    new_dump = {
        "version": 2,
        "settings": cf.settings.model_dump(),
        "profiles": [p.model_dump() for p in cf.profiles if p.id != "fps"],
    }
    new_cf = cfgmod.CommandsFileV2.model_validate(new_dump)
    reg.replace_config(new_cf)
    assert reg.active_id == "flight"
