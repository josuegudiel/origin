"""CLI / entrypoint. Sin flags lanza la GUI; `--headless` corre el engine solo.

Flags:
  --headless       Sin GUI, engine puro (Ctrl+C para salir).
  --tray           Arranca minimizado al system tray.
  --config PATH    Override de la ruta a commands.yaml (default %APPDATA%/Origin/commands.yaml).
  --log-level X    DEBUG | INFO | WARNING | ERROR (default INFO).
  --list-mics      Lista micrófonos disponibles y termina.
  --dry-run        No envía teclas reales, solo loguea (útil para tunear frases).
"""
from __future__ import annotations

import argparse
import logging
import shutil
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .engine import logging_setup
from .engine.events import EventBus
from .engine.paths import bundled_resource_dir, default_paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="origin", description=__doc__)
    p.add_argument("--headless", action="store_true", help="Sin GUI, engine puro")
    p.add_argument("--tray", action="store_true", help="Arranca minimizado al tray")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        type=str.upper,
    )
    p.add_argument("--list-mics", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--version", action="version", version=f"origin {__version__}")
    return p.parse_args(argv)


def ensure_preset(target: Path) -> bool:
    """Si target no existe, copia el preset bundled. Devuelve True si lo creó."""
    if target.exists():
        return False
    preset = bundled_resource_dir() / "commands.preset.yaml"
    if not preset.exists():
        # Fallback: buscar en el origen del repo (dev sin install).
        alt = Path(__file__).resolve().parent.parent / "commands.preset.yaml"
        if alt.exists():
            preset = alt
        else:
            raise FileNotFoundError(
                f"No se encontró el preset bundled ({preset}) y target tampoco existe ({target})"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(preset, target)
    return True


def print_mics() -> None:
    try:
        from .engine.audio import list_input_devices
        devices = list_input_devices()
    except (ImportError, OSError) as e:
        # PortAudio missing (Linux sin libportaudio2), sounddevice no instalado,
        # o cualquier otro fallo de inicialización del audio backend.
        print(f"No se pudo enumerar micrófonos: {e}", file=sys.stderr)
        print(
            "  Hint: en Linux instalá libportaudio2 (apt install libportaudio2). "
            "En Windows debería andar out-of-the-box.",
            file=sys.stderr,
        )
        return
    if not devices:
        print("No se detectaron micrófonos.")
        return
    print(f"{'idx':>4}  {'def':>3}  channels  name")
    for d in devices:
        mark = "*" if d["default"] else ""
        print(f"{d['index']:>4}  {mark:>3}  {d['channels']:>8}  {d['name']}")


def run_headless(config_path: Path, dry_run: bool) -> int:
    from .engine.runtime import Orchestrator

    bus = EventBus()
    orch = Orchestrator(config_path, bus, dry_run=dry_run)
    orch.start()

    stop = {"flag": False}

    def handler(signum: int, frame: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handler)

    logging.info("origin_running_headless config=%s — Ctrl+C para salir", config_path)
    try:
        while not stop["flag"]:
            time.sleep(0.2)
    finally:
        orch.shutdown()
    return 0


def run_gui(config_path: Path, dry_run: bool, start_minimized: bool) -> int:
    from .ui.app import run_app

    return run_app(config_path=config_path, dry_run=dry_run, start_minimized=start_minimized)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = default_paths()
    paths.ensure()
    config_path = args.config if args.config else paths.commands_yaml

    # Logging setup mínimo antes de tocar archivos — la UI/headless puede re-configurar.
    logging_setup.setup(args.log_level, paths.log_file, fmt="pretty")

    if args.list_mics:
        print_mics()
        return 0

    if args.config is None:
        try:
            created = ensure_preset(config_path)
            if created:
                logging.info("preset_copied_to %s", config_path)
        except FileNotFoundError as e:
            logging.error("%s", e)
            return 2
    elif not config_path.exists():
        # --config con path explícito que no existe → error claro, no FileNotFoundError crudo.
        print(f"Error: --config '{config_path}' no existe", file=sys.stderr)
        return 2

    try:
        if args.headless:
            return run_headless(config_path, dry_run=args.dry_run)
        return run_gui(config_path, dry_run=args.dry_run, start_minimized=args.tray)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
