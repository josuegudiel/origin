"""Validación del preset shipped — ≥200 comandos bilingues + keys válidas."""
from __future__ import annotations

from pathlib import Path

from origin.engine import config as cfgmod
from origin.engine import keypress

PRESET = Path(__file__).resolve().parent.parent.parent / "commands.preset.yaml"


def test_preset_parses_as_v3():
    cf = cfgmod.load(PRESET)
    assert cf.version == 3


def test_preset_has_200_plus_commands():
    cf = cfgmod.load(PRESET)
    total = sum(len(p.commands) for p in cf.profiles)
    assert total >= 200, f"esperaba ≥200 comandos, hay {total}"


def test_preset_has_at_least_7_profiles():
    cf = cfgmod.load(PRESET)
    assert len(cf.profiles) >= 7


def test_preset_commands_have_bilingual_phrases():
    cf = cfgmod.load(PRESET)
    fails = []
    for p in cf.profiles:
        for c in p.commands:
            if not c.phrases_es:
                fails.append((p.id, c.id, "missing phrases_es"))
            if not c.phrases_en:
                fails.append((p.id, c.id, "missing phrases_en"))
    assert not fails, f"comandos sin phrases bilingues: {fails[:5]}"


def test_preset_keys_all_parse():
    cf = cfgmod.load(PRESET)
    invalid = []
    for p in cf.profiles:
        for c in p.commands:
            for k in c.keys:
                err = keypress.validate(k)
                if err:
                    invalid.append((p.id, c.id, k, err))
    assert not invalid, f"keys inválidas en preset: {invalid[:5]}"


def test_preset_command_ids_unique_within_profile():
    cf = cfgmod.load(PRESET)
    for p in cf.profiles:
        ids = [c.id for c in p.commands]
        assert len(ids) == len(set(ids)), f"perfil {p.id} tiene ids duplicados"


def test_preset_no_misrouted_phrases():
    """REGRESSION (7ma auditoría): cada frase del preset, dicha EXACTA, debe
    rutear a SU comando — no a otro del mismo perfil.

    Antes del fix del matcher (desempate por fuzz.ratio), 27 frases ruteaban
    al comando equivocado porque token_set_ratio da 100 cuando una frase es
    subconjunto de tokens de otra: 'cierra mobiglas' ejecutaba open_mobiglas.
    """
    from origin.engine.intent import IntentMatcher

    cf = cfgmod.load(PRESET)
    threshold = cf.settings.fuzz_threshold
    misroutes = []
    for prof in cf.profiles:
        matcher = IntentMatcher(prof.commands)
        for cmd in prof.commands:
            for lang in ("es", "en"):
                for phrase in cmd.phrases_for(lang):
                    r = matcher.match(phrase, lang, threshold)
                    if r.command is None:
                        misroutes.append((prof.id, cmd.id, lang, phrase, "NO_MATCH"))
                    elif r.command.id != cmd.id:
                        misroutes.append((prof.id, cmd.id, lang, phrase, f"->{r.command.id}"))
    assert not misroutes, f"{len(misroutes)} frases mal ruteadas: {misroutes[:8]}"


def test_preset_tts_phrases_keys_exist():
    """Si algún comando usa say_key, debe existir en tts_phrases_es.json."""
    import json
    cf = cfgmod.load(PRESET)
    es_phrases_path = Path(__file__).resolve().parent.parent.parent / "origin" / "engine" / "tts_phrases_es.json"
    if not es_phrases_path.exists():
        return
    es_phrases = json.loads(es_phrases_path.read_text(encoding="utf-8"))
    missing = []
    for p in cf.profiles:
        for c in p.commands:
            if c.say_key and c.say_key not in es_phrases:
                missing.append((p.id, c.id, c.say_key))
    assert not missing, f"say_key no encontradas en tts_phrases_es.json: {missing}"
