"""Fixtures comunes para los tests de UI (PySide6 + pytest-qt)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")


@pytest.fixture
def stub_orch(tmp_path: Path, fixtures_dir: Path):
    """Construye un Orchestrator sin start() — no toca mic ni Whisper."""
    from origin.engine.events import EventBus
    from origin.engine.runtime import Orchestrator

    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    bus = EventBus()
    orch = Orchestrator(tmp_path / "commands.yaml", bus, dry_run=True)
    return orch, bus
