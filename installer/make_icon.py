"""Genera origin/ui/assets/icon.ico (emblema "punto de origen" estilo HUD).

Correr desde la raíz del repo cuando haga falta regenerarlo:
    python installer/make_icon.py

El .ico multi-tamaño lo consume:
- installer/origin.spec  → icono embebido en Origin.exe (un .exe sin icono
  genera menos confianza en el usuario y en heurísticas de AV/SmartScreen)
- installer/origin.iss   → icono del instalador/desinstalador
- origin/ui/app.py       → icono de ventana/taskbar

Requiere Pillow (solo para regenerar; no es dependencia de la app).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 1024  # lienzo de supersampling

BG = (14, 23, 38, 255)        # azul noche
CYAN = (53, 196, 231, 255)    # cian HUD
CYAN_DIM = (53, 196, 231, 90)


def draw_emblem() -> Image.Image:
    img = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = SS // 2

    # Disco de fondo.
    r_bg = 470
    d.ellipse([c - r_bg, c - r_bg, c + r_bg, c + r_bg], fill=BG)

    # Anillo exterior (la "O" de Origin / retícula).
    r_ring = 400
    w_ring = 64
    d.ellipse(
        [c - r_ring, c - r_ring, c + r_ring, c + r_ring],
        outline=CYAN, width=w_ring,
    )

    # Muescas de retícula N/E/S/O cruzando el anillo.
    tick_l, tick_w = 150, 56
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        x0 = c + dx * (r_ring - tick_l // 2) - (tick_w // 2 if dx == 0 else tick_l // 2)
        y0 = c + dy * (r_ring - tick_l // 2) - (tick_w // 2 if dy == 0 else tick_l // 2)
        x1 = x0 + (tick_w if dx == 0 else tick_l)
        y1 = y0 + (tick_w if dy == 0 else tick_l)
        d.rectangle([x0, y0, x1, y1], fill=CYAN)

    # Órbita interna tenue + punto de origen al centro.
    r_orbit = 235
    d.ellipse(
        [c - r_orbit, c - r_orbit, c + r_orbit, c + r_orbit],
        outline=CYAN_DIM, width=28,
    )
    r_dot = 92
    d.ellipse([c - r_dot, c - r_dot, c + r_dot, c + r_dot], fill=CYAN)
    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "origin" / "ui" / "assets" / "icon.ico"
    emblem = draw_emblem()
    frames = [emblem.resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(out, format="ICO", append_images=frames[:-1],
                    sizes=[(s, s) for s in SIZES])
    print(f"escrito {out} ({out.stat().st_size} bytes, tamaños {SIZES})")


if __name__ == "__main__":
    main()
