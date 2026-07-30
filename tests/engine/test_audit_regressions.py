"""Regresiones de la auditoría del núcleo (v0.3.1).

Bugs cubiertos acá: teclas que inutilizaban la app o no llegaban al juego,
modificadores que quedaban trabados, presupuesto de script compartido entre
ejecuciones, errores de config que no llegaban al usuario, `say_key` ignorado
y dispatch de comandos durante el apagado.
"""
from __future__ import annotations

import shutil
import threading
from pathlib import Path

import pytest

from origin.engine import config as cfgmod
from origin.engine import keypress
from origin.engine.events import EventBus
from origin.engine.runtime import PYNPUT_KEY_NAMES, Orchestrator

# Nombres reales del enum `Key` de pynput 1.7.x (pynput no importa sin X server,
# así que el contrato se fija acá como snapshot).
PYNPUT_KEY_ENUM = {
    "alt", "alt_gr", "alt_l", "alt_r", "backspace", "caps_lock", "cmd", "cmd_l",
    "cmd_r", "ctrl", "ctrl_l", "ctrl_r", "delete", "down", "end", "enter", "esc",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "f13", "f14", "f15", "f16", "f17", "f18", "f19", "f20", "home", "insert",
    "left", "media_next", "media_play_pause", "media_previous",
    "media_volume_down", "media_volume_mute", "media_volume_up", "menu",
    "num_lock", "page_down", "page_up", "pause", "print_screen", "right",
    "scroll_lock", "shift", "shift_l", "shift_r", "space", "tab", "up",
}

# Teclas que dejaban la app SIN listeners al elegirlas como PTT.
BRICKEABAN_LA_APP = [
    "escape", "pageup", "pagedown", "capslock", "numlock", "scrolllock",
    "printscreen", "comma", "period", "slash", "minus", "equal", "semicolon",
    "apostrophe", "leftbracket", "rightbracket", "backslash",
]


@pytest.mark.parametrize("tecla", BRICKEABAN_LA_APP)
def test_ptt_resuelve_teclas_que_antes_rompian_la_app(tecla):
    """REGRESIÓN: `_parse_pynput_key` traducía 'esc'→'escape', que NO existe en
    pynput. Elegir Esc/PageUp/coma como PTT lanzaba ValueError: la app quedaba
    sin PTT ni hotkey y, como el ajuste ya estaba persistido, tampoco arrancaba
    la próxima vez."""
    assert tecla in keypress.VALID_KEYS
    resuelto = PYNPUT_KEY_NAMES.get(tecla, tecla)
    assert resuelto in PYNPUT_KEY_ENUM or len(resuelto) == 1, (
        f"'{tecla}' → '{resuelto}' no lo resuelve pynput"
    )


def test_alias_esc_no_se_traduce_a_nombre_inexistente():
    """'esc' es el nombre REAL de pynput; traducirlo a 'escape' era el bug."""
    assert PYNPUT_KEY_NAMES.get("escape") == "esc"
    assert PYNPUT_KEY_NAMES.get("esc", "esc") == "esc"


# ------------------------------------------------------- envío real al juego

SILENCIOSAS = ["leftbracket", "rightbracket", "comma", "period", "slash",
               "semicolon", "apostrophe", "minus", "equal", "backslash"]


@pytest.mark.parametrize("tecla", SILENCIOSAS)
def test_teclas_de_puntuacion_llegan_al_backend(tecla, fake_pdi):
    """REGRESIÓN: pydirectinput no conoce 'leftbracket' y hacía `return` mudo —
    el comando se marcaba ejecutado, el log decía OK y el juego no recibía nada.
    Son binds habituales en Star Citizen."""
    keypress.execute([tecla], inter_key_delay_ms=0)
    enviados = [k for accion, k in fake_pdi.calls if accion == "press"]
    assert enviados, f"'{tecla}' no envió nada al backend"
    assert enviados[0] == keypress.PDI_KEY_NAMES[tecla]
    assert len(enviados[0]) == 1, "debe traducirse al carácter real"


def test_modificadores_se_sueltan_si_falla_un_keydown(monkeypatch):
    """REGRESIÓN: los `keyDown` de los modificadores estaban FUERA del try, así
    que una FailSafeException de pydirectinput a mitad del combo dejaba ctrl o
    shift trabados a nivel de sistema operativo."""

    class PdiQueFalla:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def keyDown(self, k: str) -> None:  # noqa: N802
            self.calls.append(("down", k))
            if k == "shift":
                raise RuntimeError("FailSafeException simulada")

        def press(self, k: str) -> None:
            self.calls.append(("press", k))

        def keyUp(self, k: str) -> None:  # noqa: N802
            self.calls.append(("up", k))

    pdi = PdiQueFalla()
    monkeypatch.setattr(keypress, "_get_pdi", lambda: pdi)
    with pytest.raises(RuntimeError):
        keypress.execute(["ctrl+shift+a"], inter_key_delay_ms=0)

    bajados = [k for a, k in pdi.calls if a == "down"]
    subidos = [k for a, k in pdi.calls if a == "up"]
    assert "ctrl" in bajados
    assert "ctrl" in subidos, "ctrl quedó presionado tras la excepción"


def test_held_suelta_todo_si_falla(monkeypatch):
    class PdiQueFallaEnKey:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def keyDown(self, k: str) -> None:  # noqa: N802
            self.calls.append(("down", k))
            if k == "b":
                raise RuntimeError("falla en la tecla final")

        def keyUp(self, k: str) -> None:  # noqa: N802
            self.calls.append(("up", k))

    pdi = PdiQueFallaEnKey()
    monkeypatch.setattr(keypress, "_get_pdi", lambda: pdi)
    with pytest.raises(RuntimeError):
        keypress.execute_held("ctrl+b", hold_ms=10)
    assert ("up", "ctrl") in pdi.calls


# ------------------------------------------- presupuesto del ejecutor de steps


def test_presupuesto_de_script_no_se_comparte_entre_ejecuciones():
    """REGRESIÓN: `_steps_run`/`_deadline` eran estado de INSTANCIA y hay una
    sola instancia de StepExecutor; con ejecuciones concurrentes (voz + botón
    Test + gestos) se repartían los 100 pasos y los scripts salían truncados."""
    from origin.engine.script import StepExecutionState, StepExecutor

    enviadas: list[str] = []
    lock = threading.Lock()

    def fake_keypress(combos, delay, dry):
        with lock:
            enviadas.extend(combos)

    ex = StepExecutor(
        keypress_exec=fake_keypress,
        keypress_exec_held=lambda c, ms, dry: None,
        tts_say=lambda *a, **k: None,
        tts_cancel=lambda: None,
        set_substate=lambda s: None,
        bus=EventBus(),
        settings_provider=lambda: cfgmod.Settings(),
        i18n_say=lambda key, lang: None,
        dry_run=True,
    )
    steps = [cfgmod.KeyStep(combo="a") for _ in range(25)]
    hilos = [
        threading.Thread(
            target=ex.execute,
            args=(list(steps), StepExecutionState(), "es"),
            kwargs={"cancel": threading.Event()},
        )
        for _ in range(3)
    ]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=10)
    assert len(enviadas) == 75, f"esperaba 3x25 pulsaciones, hubo {len(enviadas)}"


# ---------------------------------------------------------------- config


def test_yaml_no_utf8_da_config_error_visible(tmp_path: Path):
    """REGRESIÓN: Notepad guarda en ANSI por defecto; el UnicodeDecodeError NO
    era ConfigError, así que `reload_config` no lo capturaba y el usuario no
    veía ningún aviso — la app seguía con la config vieja en silencio."""
    p = tmp_path / "commands.yaml"
    p.write_bytes("version: 3\nsettings: {}\nprofiles: []\n# acción\n".encode("cp1252"))
    with pytest.raises(cfgmod.ConfigError) as ei:
        cfgmod.load(p)
    assert "UTF-8" in str(ei.value)


def test_reload_config_reporta_el_error_y_no_explota(tmp_path: Path, fixtures_dir: Path):
    from origin.engine.events import EventType

    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    bus = EventBus()
    errores: list[str] = []
    bus.subscribe(EventType.CONFIG_ERROR, lambda p: errores.append(p["error"]))
    orch = Orchestrator(tmp_path / "commands.yaml", bus, dry_run=True)

    (tmp_path / "commands.yaml").write_bytes("version: 3\nprofiles: []\n# ó\n".encode("cp1252"))
    assert orch.reload_config() is False
    assert errores and "UTF-8" in errores[0]


def test_say_key_se_traduce_a_step(tmp_path: Path):
    """REGRESIÓN: `command_as_steps` ignoraba `say_key`, así que un comando con
    frase del banco pronunciaba su label o se quedaba mudo."""
    cmd = cfgmod.Command.model_validate({
        "id": "c", "phrases_es": ["x"], "keys": ["a"],
        "say_key": "hangar_ok", "label_es": "Etiqueta",
    })
    steps = cfgmod.command_as_steps(cmd, cfgmod.Settings())
    tipos = [getattr(s, "type", None) for s in steps]
    assert "say_key" in tipos, f"say_key perdido, salió {tipos}"
    say = next(s for s in steps if getattr(s, "type", None) == "say_key")
    assert say.key == "hangar_ok"


def test_save_atomic_escribe_el_contenido_completo(tmp_path: Path, fixtures_dir: Path):
    """El guardado sincroniza a disco antes del rename (sin fsync, un corte de
    luz podía dejar commands.yaml truncado y los v3 no tienen backup)."""
    cf = cfgmod.load(fixtures_dir / "commands_v2_minimal.yaml")
    out = tmp_path / "commands.yaml"
    cfgmod.save_atomic(cf, out)
    recargado = cfgmod.load(out)
    assert len(recargado.profiles) == len(cf.profiles)
    assert recargado.to_dump() == cf.to_dump()   # nada truncado
    # No quedan temporales sueltos.
    assert not list(tmp_path.glob(".commands-*"))


# ------------------------------------------------------- shutdown en vuelo


def test_dispatch_durante_shutdown_no_ejecuta_teclas(tmp_path: Path, fixtures_dir: Path):
    """REGRESIÓN: `_dispatch_command` hacía `_script_cancel.clear()`, borrando el
    cancel que el shutdown acababa de activar — el script seguía inyectando
    teclas en la ventana en foco mientras la app se cerraba."""
    from origin.engine.events import EventType

    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    bus = EventBus()
    ejecutados: list[str] = []
    bus.subscribe(EventType.COMMAND_EXECUTED, lambda p: ejecutados.append(p["command_id"]))
    orch = Orchestrator(tmp_path / "commands.yaml", bus, dry_run=True)
    orch._build_tts()
    orch._build_script_executor()

    orch._shutting_down = True
    orch._script_cancel.set()
    cmd = orch.config.get_profile("flight").commands[0]
    orch._dispatch_command(cmd, "es")
    assert ejecutados == [], "no debía ejecutar nada durante el apagado"


def test_dispatch_normal_si_no_hay_shutdown(tmp_path: Path, fixtures_dir: Path):
    from origin.engine.events import EventType

    shutil.copy(fixtures_dir / "commands_v2_minimal.yaml", tmp_path / "commands.yaml")
    bus = EventBus()
    ejecutados: list[str] = []
    bus.subscribe(EventType.COMMAND_EXECUTED, lambda p: ejecutados.append(p["command_id"]))
    orch = Orchestrator(tmp_path / "commands.yaml", bus, dry_run=True)
    orch._build_tts()
    orch._build_script_executor()
    cmd = orch.config.get_profile("flight").commands[0]
    orch._dispatch_command(cmd, "es")
    assert ejecutados == ["request_landing"]
