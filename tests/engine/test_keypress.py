"""Tests del módulo keypress (parse, validate, execute con pdi mockeado)."""
from __future__ import annotations

import pytest

from origin.engine import keypress
from origin.engine.keypress import KeyError_, parse_combo, validate


def test_parse_simple_key():
    mods, key = parse_combo("n")
    assert mods == [] and key == "n"


def test_parse_with_modifier():
    mods, key = parse_combo("alt+n")
    assert mods == ["alt"] and key == "n"


def test_modifier_order_is_deterministic():
    mods, key = parse_combo("alt+shift+ctrl+x")
    assert mods == ["ctrl", "shift", "alt"] and key == "x"


def test_function_keys():
    _mods, key = parse_combo("f12")
    assert key == "f12"


def test_aliases():
    _, key = parse_combo("esc")
    assert key == "escape"
    _, key = parse_combo("return")
    assert key == "enter"


def test_validate_returns_none_when_ok():
    assert validate("alt+n") is None


def test_validate_returns_error_message_when_invalid():
    err = validate("alt+ctrl")
    assert err and "modificadores" in err


def test_only_modifiers_combo_rejected():
    with pytest.raises(KeyError_):
        parse_combo("ctrl+shift")


def test_unknown_key_rejected():
    with pytest.raises(KeyError_):
        parse_combo("zzzzz")


def test_duplicate_modifier_rejected():
    with pytest.raises(KeyError_):
        parse_combo("ctrl+ctrl+x")


def test_execute_combo_order(fake_pdi):
    keypress.execute(["ctrl+shift+x"], inter_key_delay_ms=0)
    assert fake_pdi.calls == [
        ("down", "ctrl"),
        ("down", "shift"),
        ("press", "x"),
        ("up", "shift"),
        ("up", "ctrl"),
    ]


def test_execute_sequence(fake_pdi):
    keypress.execute(["alt+n", "y"], inter_key_delay_ms=0)
    assert fake_pdi.calls == [
        ("down", "alt"),
        ("press", "n"),
        ("up", "alt"),
        ("press", "y"),
    ]


def test_execute_dry_run_does_not_call_pdi(fake_pdi):
    keypress.execute(["alt+n"], inter_key_delay_ms=0, dry_run=True)
    assert fake_pdi.calls == []
