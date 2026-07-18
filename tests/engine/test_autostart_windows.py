"""Tests de autostart_windows. Solo se ejecutan en Windows; en otros SO se skipean."""
from __future__ import annotations

import sys

import pytest

from origin.engine import autostart_windows


def test_is_supported_matches_platform():
    assert autostart_windows.is_supported() == (sys.platform == "win32")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_write_remove_run_key_roundtrip():
    autostart_windows.remove_run_key()
    assert not autostart_windows.is_enabled()
    autostart_windows.write_run_key()
    assert autostart_windows.is_enabled()
    autostart_windows.remove_run_key()
    assert not autostart_windows.is_enabled()


def test_no_op_on_non_windows():
    if sys.platform == "win32":
        pytest.skip("Solo prueba el branch no-Windows")
    # No deberían explotar ni hacer nada.
    autostart_windows.write_run_key()
    autostart_windows.remove_run_key()
    assert autostart_windows.is_enabled() is False
