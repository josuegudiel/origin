"""Tests del schema v3: Step types, nested settings, migración v2→v3."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from origin.engine import config as cfgmod


def test_v3_with_nested_settings_loads(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(
        """
version: 3
settings:
  active_profile: p1
  tts: {enabled: false}
  hotas: {enabled: true, button_binding: "0:BTN_THUMB"}
  llm: {enabled: true, model: "phi3"}
profiles:
  - id: p1
    commands:
      - id: c1
        phrases_es: ["x"]
        keys: ["a"]
""",
        encoding="utf-8",
    )
    cf = cfgmod.load(p)
    assert cf.version == 3
    assert cf.settings.tts.enabled is False
    assert cf.settings.hotas.enabled is True
    assert cf.settings.hotas.button_binding == "0:BTN_THUMB"
    assert cf.settings.llm.model == "phi3"


def test_v2_loads_with_v3_schema_defaults(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(
        """
version: 2
settings:
  active_profile: p1
profiles:
  - id: p1
    commands:
      - id: c1
        phrases_es: ["x"]
        keys: ["a"]
""",
        encoding="utf-8",
    )
    cf = cfgmod.load(p)
    # v2 sigue cargando, las sub-settings toman defaults v3
    assert cf.settings.tts.enabled is True
    assert cf.settings.hotas.enabled is False
    assert cf.settings.llm.enabled is False
    # backup v2 escrito
    assert (tmp_path / "commands.v2.backup.yaml").exists()


def test_step_types_parse_via_discriminator():
    from origin.engine.config import IfStep, KeyStep, SayStep, SetStep, WaitStep
    raw = {
        "version": 3,
        "settings": {"active_profile": "p1"},
        "profiles": [{
            "id": "p1",
            "commands": [{
                "id": "complex",
                "phrases_es": ["test"],
                "keys": ["a"],
                "steps": [
                    {"type": "key", "combo": "alt+n"},
                    {"type": "wait", "ms": 100},
                    {"type": "say", "text_es": "hola"},
                    {"type": "set", "var": "x", "value": "1"},
                    {"type": "if", "cond": "x == '1'", "then": [
                        {"type": "key", "combo": "b"},
                    ]},
                ],
            }],
        }],
    }
    cf = cfgmod.CommandsFileV3.model_validate(raw)
    steps = cf.profiles[0].commands[0].steps
    assert isinstance(steps[0], KeyStep)
    assert isinstance(steps[1], WaitStep)
    assert isinstance(steps[2], SayStep)
    assert isinstance(steps[3], SetStep)
    assert isinstance(steps[4], IfStep)


def test_step_count_tope_100_enforced():
    long_steps = [{"type": "key", "combo": "a"} for _ in range(101)]
    raw = {
        "version": 3, "settings": {"active_profile": "p1"},
        "profiles": [{"id": "p1", "commands": [{
            "id": "huge", "phrases_es": ["x"], "keys": ["a"], "steps": long_steps,
        }]}],
    }
    with pytest.raises(Exception):
        cfgmod.CommandsFileV3.model_validate(raw)


def test_repeat_expands_for_step_tope():
    # 50 inner × repeat 3 = 150 > 100
    inner = [{"type": "key", "combo": "a"} for _ in range(50)]
    raw = {
        "version": 3, "settings": {"active_profile": "p1"},
        "profiles": [{"id": "p1", "commands": [{
            "id": "with_repeat", "phrases_es": ["x"], "keys": ["a"],
            "steps": [{"type": "repeat", "times": 3, "steps": inner}],
        }]}],
    }
    with pytest.raises(Exception):
        cfgmod.CommandsFileV3.model_validate(raw)


def test_command_with_only_steps_is_valid(tmp_path: Path):
    # `keys` puede estar vacío si hay `steps`.
    raw = {
        "version": 3, "settings": {"active_profile": "p1"},
        "profiles": [{"id": "p1", "commands": [{
            "id": "c", "phrases_es": ["x"], "steps": [{"type": "key", "combo": "a"}],
        }]}],
    }
    cf = cfgmod.CommandsFileV3.model_validate(raw)
    assert cf.profiles[0].commands[0].keys == []


def test_with_settings_nested_merge():
    cf = cfgmod.CommandsFileV3.model_validate({
        "version": 3, "settings": {"active_profile": "p1"},
        "profiles": [{"id": "p1", "commands": [{"id": "c", "phrases_es": ["x"], "keys": ["a"]}]}],
    })
    new_cf = cf.with_settings(tts={"enabled": False, "volume": 0.5})
    assert new_cf.settings.tts.enabled is False
    assert new_cf.settings.tts.volume == 0.5
    # otros campos del tts mantienen defaults
    assert new_cf.settings.tts.voice_es == "es_ES-mls_10246-low"
    # original inmutable
    assert cf.settings.tts.enabled is True


def test_command_as_steps_translates_keys_to_steps(tmp_path: Path):
    cf = cfgmod.CommandsFileV3.model_validate({
        "version": 3, "settings": {"active_profile": "p1", "inter_key_delay_ms": 30},
        "profiles": [{"id": "p1", "commands": [{
            "id": "c", "phrases_es": ["x"], "keys": ["alt+n", "y"], "say_es": "ack",
            "label_es": "Test",
        }]}],
    })
    cmd = cf.profiles[0].commands[0]
    steps = cfgmod.command_as_steps(cmd, cf.settings)
    # 2 keys + 1 wait entre ellas + 1 say = 4
    assert len(steps) == 4
    from origin.engine.config import KeyStep, SayStep, WaitStep
    assert isinstance(steps[0], KeyStep) and steps[0].combo == "alt+n"
    assert isinstance(steps[1], WaitStep) and steps[1].ms == 30
    assert isinstance(steps[2], KeyStep) and steps[2].combo == "y"
    assert isinstance(steps[3], SayStep)
