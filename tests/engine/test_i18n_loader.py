"""Tests del loader de strings i18n."""
from __future__ import annotations

import json
from pathlib import Path

from origin.engine.i18n_loader import load_strings


def test_load_existing_lang(tmp_path: Path):
    (tmp_path / "es.json").write_text(json.dumps({"k": "valor"}), encoding="utf-8")
    assert load_strings(tmp_path, "es") == {"k": "valor"}


def test_load_handles_utf8_bom(tmp_path: Path):
    """REGRESSION: editores en Windows (Notepad) agregan BOM UTF-8 al guardar
    JSON. Sin utf-8-sig el load crashea con JSONDecodeError."""
    (tmp_path / "es.json").write_bytes(b"\xef\xbb\xbf" + b'{"k": "valor"}')
    assert load_strings(tmp_path, "es") == {"k": "valor"}


def test_load_missing_returns_empty(tmp_path: Path):
    assert load_strings(tmp_path, "xx") == {}


def test_real_es_and_en_have_required_keys():
    """Smoke: las traducciones ES/EN reales tienen claves mínimas para no quedar como key raw."""
    from origin.ui.i18n import tr as trmod

    es = load_strings(Path(trmod._I18N_DIR), "es")  # type: ignore[attr-defined]
    en = load_strings(Path(trmod._I18N_DIR), "en")  # type: ignore[attr-defined]
    must_have = {
        "state.ready",
        "state.recording",
        "sidebar.dashboard",
        "sidebar.commands",
        "sidebar.profiles",
        "header.pause",
        "tray.show_dashboard",
        "tray.quit",
    }
    assert must_have <= set(es.keys()), f"faltan en ES: {must_have - set(es.keys())}"
    # EN puede tener faltantes (caen al fallback ES), pero debe cubrir ≥90%.
    missing_in_en = set(es.keys()) - set(en.keys())
    coverage = 1 - len(missing_in_en) / len(es)
    assert coverage >= 0.9, f"cobertura EN insuficiente: {coverage:.2%}, faltan: {missing_in_en}"
