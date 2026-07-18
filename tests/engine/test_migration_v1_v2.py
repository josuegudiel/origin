"""Tests de migración v1 → v2."""
from __future__ import annotations

import shutil
from pathlib import Path

from origin.engine import config as cfgmod


def test_v1_migrates_to_single_default_profile(fixtures_dir: Path, tmp_path: Path):
    src = fixtures_dir / "commands_v1_minimal.yaml"
    dst = tmp_path / "commands.yaml"
    shutil.copy(src, dst)
    cf = cfgmod.load(dst)
    assert cf.version == 3  # v1 ahora migra directo a v3
    assert len(cf.profiles) == 1
    assert cf.profiles[0].id == "default"
    assert cf.settings.active_profile == "default"
    # active_language migrado desde el legacy `language`
    assert cf.settings.active_language == "es"
    assert {c.id for c in cf.profiles[0].commands} == {"request_landing", "toggle_lights"}
    # Comandos migrados: phrases_es se copia de phrases v1; phrases_en queda vacío.
    rl = next(c for c in cf.profiles[0].commands if c.id == "request_landing")
    assert rl.phrases_es == ["pide hangar", "solicita aterrizaje"]
    assert rl.phrases_en == []


def test_v1_migration_writes_backup_next_to_source(fixtures_dir: Path, tmp_path: Path):
    src = fixtures_dir / "commands_v1_minimal.yaml"
    dst = tmp_path / "commands.yaml"
    shutil.copy(src, dst)
    cfgmod.load(dst)
    backup = tmp_path / "commands.v1.backup.yaml"
    assert backup.exists()
    # No sobreescribe en segundas cargas.
    backup_mtime = backup.stat().st_mtime
    cfgmod.load(dst)
    assert backup.stat().st_mtime == backup_mtime
