"""Tests del modelo Pydantic y de save_atomic."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from origin.engine import config as cfgmod


def test_load_v2_minimal(fixtures_dir: Path):
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    assert cf.version == 2
    assert {p.id for p in cf.profiles} == {"flight", "fps"}
    assert cf.settings.active_profile == "flight"


def test_v2_active_profile_must_exist(fixtures_dir: Path):
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(fixtures_dir / "commands_v2_invalid.yaml")


def test_extra_forbid_on_settings():
    with pytest.raises(Exception):
        cfgmod.Settings(extra_unknown_field=1)


def test_extra_forbid_on_command():
    with pytest.raises(Exception):
        cfgmod.Command(id="x", phrases_es=["a"], keys=["a"], extra_field="oops")


def test_command_requires_at_least_one_phrase():
    with pytest.raises(Exception):
        cfgmod.Command(id="x", phrases_es=[], phrases_en=[], keys=["a"])


def test_command_keys_normalize_lowercase():
    c = cfgmod.Command(id="x", phrases_es=["x"], keys=["Alt+N", "L"])
    assert c.keys == ["alt+n", "l"]


def test_duplicate_command_ids_within_profile_rejected():
    with pytest.raises(Exception):
        cfgmod.Profile.model_validate(
            {
                "id": "p1",
                "commands": [
                    {"id": "c", "phrases_es": ["x"], "keys": ["a"]},
                    {"id": "c", "phrases_es": ["y"], "keys": ["b"]},
                ],
            }
        )


def test_duplicate_profile_ids_rejected():
    with pytest.raises(Exception):
        cfgmod.CommandsFileV2.model_validate(
            {
                "version": 2,
                "settings": {"active_profile": "p1"},
                "profiles": [
                    {"id": "p1", "commands": [{"id": "c", "phrases_es": ["x"], "keys": ["a"]}]},
                    {"id": "p1", "commands": [{"id": "c", "phrases_es": ["y"], "keys": ["b"]}]},
                ],
            }
        )


def test_save_atomic_roundtrip(fixtures_dir: Path, tmp_path: Path):
    src = fixtures_dir / "commands_v2_minimal.yaml"
    dst = tmp_path / "commands.yaml"
    shutil.copy(src, dst)
    cf = cfgmod.load(dst)
    out = tmp_path / "out.yaml"
    cfgmod.save_atomic(cf, out)
    reloaded = cfgmod.load(out)
    assert reloaded.profiles[0].id == cf.profiles[0].id
    assert reloaded.settings.active_profile == cf.settings.active_profile


def test_save_atomic_does_not_leave_tmp_on_success(fixtures_dir: Path, tmp_path: Path):
    src = fixtures_dir / "commands_v2_minimal.yaml"
    cf = cfgmod.load(src)
    out = tmp_path / "commands.yaml"
    cfgmod.save_atomic(cf, out)
    assert out.exists()
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".commands-")]
    assert not leftovers


def test_invalid_yaml_raises_config_error(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("version: 2\nprofiles: [\n", encoding="utf-8")  # YAML inválido
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load(p)


def test_with_settings_changes_only_settings(fixtures_dir: Path):
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    new_cf = cf.with_settings(active_language="en")
    assert new_cf.settings.active_language == "en"
    assert cf.settings.active_language == "es"  # original inmutable
    assert [p.id for p in new_cf.profiles] == [p.id for p in cf.profiles]
