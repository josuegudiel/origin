"""Fixtures compartidos para los tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    return tmp_path / "commands.yaml"


@pytest.fixture(autouse=True)
def _clean_origin_imports():
    """Resetea el cache de logging entre tests."""
    import logging

    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)
    yield


@pytest.fixture
def fake_pdi(monkeypatch):
    """Reemplaza pydirectinput por un mock que registra cada keyDown/press/keyUp."""

    class FakePdi:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def keyDown(self, k: str) -> None:  # noqa: N802
            self.calls.append(("down", k))

        def press(self, k: str) -> None:
            self.calls.append(("press", k))

        def keyUp(self, k: str) -> None:  # noqa: N802
            self.calls.append(("up", k))

    fake = FakePdi()
    monkeypatch.setattr("origin.engine.keypress._get_pdi", lambda: fake)
    return fake
