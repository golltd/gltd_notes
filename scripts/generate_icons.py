#!/usr/bin/env python3
"""Generate GLTD Notes icon set (Pillow) — crisp, menu-ready PNGs."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

# Palette — deep indigo + mint accent (private notes, blockchain chain)
BG_TOP = (30, 41, 72, 255)
BG_BOT = (18, 24, 48, 255)
ACCENT = (94, 200, 168, 255)
ACCENT2 = (122, 162, 247, 255)
PAPER = (245, 247, 252, 255)
INK = (40, 48, 72, 255)
CHAIN = (94, 200, 168, 255)
WHITE = (255, 255, 255, 255)


def _font(size: int):
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ):
        p = Path(name)
        if p.exists():
            return ImageFont.truetype(str(p), size=size)
    return ImageFont.load_default()


def _gradient(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG_BOT)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))
    return img


def _rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    x0, y0, x1, y1 = [int(round(v)) for v in xy]
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    if x1 - x0 < 1 or y1 - y0 < 1:
        return
    # Older Pillow can break on large radius relative to short side
    r = max(0, min(int(radius), (x1 - x0) // 2, (y1 - y0) // 2))
    if r <= 0 or (y1 - y0) < 4 or (x1 - x0) < 4:
        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=width)
        return
    try:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)
    except ValueError:
        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=width)


def draw_app_icon(size: int) -> Image.Image:
    img = _gradient(size)
    draw = ImageDraw.Draw(img)
    m = size * 0.12
    # soft glow circle
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx = cy = size // 2
    gd.ellipse([cx - size * 0.4, cy - size * 0.4, cx + size * 0.4, cy + size * 0.4], fill=(*ACCENT2[:3], 40))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=size * 0.08))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # notebook page
    pad = size * 0.18
    page = [pad, pad * 0.95, size - pad * 0.85, size - pad * 0.75]
    _rounded_rect(draw, page, radius=size * 0.08, fill=PAPER, outline=ACCENT2, width=max(1, size // 64))

    # spiral / left margin stripe
    stripe_x = pad + size * 0.06
    draw.rectangle([pad, page[1], stripe_x, page[3]], fill=(*ACCENT[:3], 55))
    for i in range(4):
        y = page[1] + size * (0.18 + i * 0.16)
        r = size * 0.035
        draw.ellipse([stripe_x - r, y - r, stripe_x + r, y + r], fill=ACCENT2)

    # text lines
    lx0 = pad + size * 0.16
    lx1 = size - pad * 1.05
    for i in range(5):
        y = page[1] + size * (0.22 + i * 0.1)
        w = (lx1 - lx0) * (0.95 if i < 4 else 0.55)
        draw.rounded_rectangle([lx0, y, lx0 + w, y + size * 0.035], radius=2, fill=(*INK[:3], 50 if i else 90))

    # blockchain nodes (bottom-right chain)
    nodes = []
    for i in range(4):
        nx = size * (0.42 + i * 0.12)
        ny = size * 0.78
        nodes.append((nx, ny))
    for i in range(len(nodes) - 1):
        draw.line([nodes[i], nodes[i + 1]], fill=CHAIN, width=max(2, size // 48))
    for nx, ny in nodes:
        r = size * 0.045
        draw.ellipse([nx - r, ny - r, nx + r, ny + r], fill=ACCENT, outline=WHITE, width=max(1, size // 80))

    # monogram G
    try:
        font = _font(max(10, int(size * 0.22)))
        draw.text((size * 0.58, size * 0.28), "G", font=font, fill=ACCENT2)
    except Exception:
        pass

    # circular mask for largest sizes looks modern; keep square with rounded corners for desktop
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.18, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, mask=mask)
    return out


def draw_simple_icon(kind: str, size: int) -> Image.Image:
    # Always draw large then downscale for crisp small sizes
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = S * 0.08
    bg = BG_TOP
    _rounded_rect(draw, [m, m, S - m, S - m], radius=S * 0.2, fill=bg)

    c = ACCENT
    c2 = ACCENT2
    s = S

    if kind == "note-new":
        _rounded_rect(draw, [s * 0.28, s * 0.2, s * 0.72, s * 0.78], radius=s * 0.06, fill=PAPER)
        draw.line([(s * 0.5, s * 0.38), (s * 0.5, s * 0.62)], fill=c, width=max(2, s // 16))
        draw.line([(s * 0.38, s * 0.5), (s * 0.62, s * 0.5)], fill=c, width=max(2, s // 16))
    elif kind == "note-save":
        _rounded_rect(draw, [s * 0.25, s * 0.22, s * 0.75, s * 0.78], radius=s * 0.05, fill=c2)
        _rounded_rect(draw, [s * 0.35, s * 0.22, s * 0.65, s * 0.42], radius=4, fill=PAPER)
        _rounded_rect(draw, [s * 0.32, s * 0.5, s * 0.68, s * 0.72], radius=4, fill=PAPER)
    elif kind == "note-delete":
        draw.rectangle([s * 0.3, s * 0.35, s * 0.7, s * 0.78], fill=(*c2[:3], 220))
        draw.rectangle([s * 0.25, s * 0.28, s * 0.75, s * 0.38], fill=c)
        draw.rectangle([s * 0.42, s * 0.2, s * 0.58, s * 0.3], fill=c)
    elif kind == "share":
        pts = [(s * 0.3, s * 0.3), (s * 0.7, s * 0.5), (s * 0.3, s * 0.7)]
        draw.line([pts[0], pts[1]], fill=c, width=max(2, s // 20))
        draw.line([pts[1], pts[2]], fill=c, width=max(2, s // 20))
        for x, y in pts:
            r = s * 0.09
            draw.ellipse([x - r, y - r, x + r, y + r], fill=c2)
    elif kind == "attach":
        draw.arc([s * 0.32, s * 0.22, s * 0.68, s * 0.78], 200, 520, fill=c, width=max(3, s // 14))
        draw.arc([s * 0.4, s * 0.32, s * 0.6, s * 0.68], 200, 520, fill=c2, width=max(2, s // 18))
    elif kind == "event":
        _rounded_rect(draw, [s * 0.22, s * 0.28, s * 0.78, s * 0.8], radius=s * 0.06, fill=PAPER)
        draw.rectangle([s * 0.22, s * 0.28, s * 0.78, s * 0.42], fill=c)
        for col in range(3):
            for row in range(2):
                x = s * (0.32 + col * 0.16)
                y = s * (0.5 + row * 0.14)
                draw.ellipse(
                    [x, y, x + s * 0.08, y + s * 0.08],
                    fill=c2 if row == 0 and col == 1 else (*INK[:3], 80),
                )
    elif kind == "refresh":
        draw.arc([s * 0.25, s * 0.25, s * 0.75, s * 0.75], 40, 280, fill=c, width=max(3, s // 12))
        draw.polygon(
            [(s * 0.72, s * 0.28), (s * 0.85, s * 0.38), (s * 0.68, s * 0.45)],
            fill=c2,
        )
    elif kind == "lock":
        draw.arc([s * 0.32, s * 0.18, s * 0.68, s * 0.52], 0, 360, fill=c2, width=max(3, s // 14))
        _rounded_rect(draw, [s * 0.28, s * 0.42, s * 0.72, s * 0.82], radius=s * 0.06, fill=c)
        draw.ellipse([s * 0.44, s * 0.52, s * 0.56, s * 0.64], fill=PAPER)
        draw.rectangle([s * 0.47, s * 0.6, s * 0.53, s * 0.74], fill=PAPER)
    elif kind == "settings":
        cx = cy = s / 2
        r_out = s * 0.32
        r_in = s * 0.14
        for i in range(8):
            ang = i * math.pi / 4
            x = cx + math.cos(ang) * r_out
            y = cy + math.sin(ang) * r_out
            draw.ellipse([x - s * 0.08, y - s * 0.08, x + s * 0.08, y + s * 0.08], fill=c2)
        draw.ellipse([cx - r_out * 0.7, cy - r_out * 0.7, cx + r_out * 0.7, cy + r_out * 0.7], fill=c)
        draw.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=BG_TOP)
    elif kind == "search":
        draw.ellipse([s * 0.22, s * 0.2, s * 0.62, s * 0.6], outline=c, width=max(3, s // 14))
        draw.line([(s * 0.55, s * 0.55), (s * 0.78, s * 0.78)], fill=c2, width=max(3, s // 12))
    elif kind == "history":
        draw.ellipse([s * 0.22, s * 0.22, s * 0.78, s * 0.78], outline=c2, width=max(3, s // 14))
        draw.line([(s * 0.5, s * 0.32), (s * 0.5, s * 0.52)], fill=c, width=max(2, s // 16))
        draw.line([(s * 0.5, s * 0.52), (s * 0.68, s * 0.6)], fill=c, width=max(2, s // 16))
    elif kind == "agent-task":
        # bot head silhouette
        _rounded_rect(draw, [s * 0.28, s * 0.32, s * 0.72, s * 0.78], radius=s * 0.08, fill=c2)
        # antenna
        draw.line([(s * 0.5, s * 0.32), (s * 0.5, s * 0.22)], fill=c, width=max(2, s // 18))
        draw.ellipse([s * 0.46, s * 0.17, s * 0.54, s * 0.25], fill=c)
        # eyes
        draw.ellipse([s * 0.36, s * 0.42, s * 0.44, s * 0.5], fill=PAPER)
        draw.ellipse([s * 0.56, s * 0.42, s * 0.64, s * 0.5], fill=PAPER)
        # pupils
        draw.ellipse([s * 0.39, s * 0.44, s * 0.41, s * 0.48], fill=INK)
        draw.ellipse([s * 0.59, s * 0.44, s * 0.61, s * 0.48], fill=INK)
        # mouth / circuit
        for i in range(3):
            y = s * (0.57 + i * 0.07)
            w = s * (0.14 - i * 0.02)
            x0 = s * 0.5 - w
            x1 = s * 0.5 + w
            draw.rounded_rectangle([x0, y, x1, y + s * 0.03], radius=2, fill=PAPER)
    else:
        return draw_app_icon(size)

    if size != S:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def draw_service_icon(kind: str, size: int) -> Image.Image:
    """Distinct icons for GUI / API / Web launchers."""
    # Base app mark
    base = draw_app_icon(max(size, 256) if size < 64 else size)
    if size != base.size[0]:
        base = base.resize((size, size), Image.Resampling.LANCZOS)

    # Work at 256 then scale for badge clarity
    S = 256
    canvas = base.resize((S, S), Image.Resampling.LANCZOS) if base.size[0] != S else base.copy()
    draw = ImageDraw.Draw(canvas)

    # Badge circle bottom-right
    br = int(S * 0.22)
    bx, by = S - br - int(S * 0.08), S - br - int(S * 0.08)
    if kind == "api":
        badge = (232, 140, 70, 255)  # amber — service
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=badge, outline=WHITE, width=max(2, S // 64))
        # plug / node: three lines
        draw.line([(bx - br * 0.35, by), (bx + br * 0.35, by)], fill=WHITE, width=max(3, S // 40))
        draw.line([(bx, by - br * 0.35), (bx, by + br * 0.35)], fill=WHITE, width=max(3, S // 40))
        draw.ellipse([bx - br * 0.2, by - br * 0.2, bx + br * 0.2, by + br * 0.2], fill=WHITE)
    elif kind == "web":
        badge = (90, 170, 230, 255)  # sky — browser
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=badge, outline=WHITE, width=max(2, S // 64))
        # globe rings
        draw.ellipse([bx - br * 0.55, by - br * 0.55, bx + br * 0.55, by + br * 0.55], outline=WHITE, width=max(2, S // 50))
        draw.ellipse([bx - br * 0.25, by - br * 0.55, bx + br * 0.25, by + br * 0.55], outline=WHITE, width=max(2, S // 55))
        draw.line([(bx - br * 0.55, by), (bx + br * 0.55, by)], fill=WHITE, width=max(2, S // 55))
    else:  # gui
        badge = ACCENT
        draw.ellipse([bx - br, by - br, bx + br, by + br], fill=badge, outline=WHITE, width=max(2, S // 64))
        # window
        _rounded_rect(
            draw,
            [bx - br * 0.45, by - br * 0.4, bx + br * 0.45, by + br * 0.4],
            radius=S * 0.02,
            fill=PAPER,
        )
        draw.rectangle([bx - br * 0.45, by - br * 0.4, bx + br * 0.45, by - br * 0.15], fill=ACCENT2)

    if size != S:
        canvas = canvas.resize((size, size), Image.Resampling.LANCZOS)
    return canvas


def save_all():
    OUT.mkdir(parents=True, exist_ok=True)
    kinds = [
        "app",
        "note-new",
        "note-save",
        "note-delete",
        "share",
        "attach",
        "event",
        "refresh",
        "lock",
        "settings",
        "search",
        "history",
        "agent-task",
    ]
    name_map = {
        "app": "gltd-notes",
        "note-new": "gltd-note-new",
        "note-save": "gltd-note-save",
        "note-delete": "gltd-note-delete",
        "share": "gltd-share",
        "attach": "gltd-attach",
        "event": "gltd-event",
        "refresh": "gltd-refresh",
        "lock": "gltd-lock",
        "settings": "gltd-settings",
        "search": "gltd-search",
        "history": "gltd-history",
        "agent-task": "gltd-agent-task",
    }
    for kind in kinds:
        stem = name_map[kind]
        master = draw_app_icon(512) if kind == "app" else draw_simple_icon(kind, 256)
        master.save(OUT / f"{stem}.png")
        for sz in SIZES:
            im = draw_app_icon(sz) if kind == "app" else draw_simple_icon(kind, sz)
            im.save(OUT / f"{stem}-{sz}.png")
        print(f"wrote {stem}")

    # Launcher / service icons
    service_map = {
        "gui": "gltd-notes-gui",
        "api": "gltd-notes-api",
        "web": "gltd-notes-web",
    }
    for kind, stem in service_map.items():
        master = draw_service_icon(kind, 512)
        master.save(OUT / f"{stem}.png")
        for sz in SIZES:
            draw_service_icon(kind, sz).save(OUT / f"{stem}-{sz}.png")
        print(f"wrote {stem}")

    # hicolor-style tree for desktop integration
    hicolor = OUT / "hicolor"
    app_icons = {
        "gltd-notes": "gltd-notes",
        "gltd-notes-gui": "gltd-notes-gui",
        "gltd-notes-api": "gltd-notes-api",
        "gltd-notes-web": "gltd-notes-web",
    }
    for sz in (16, 24, 32, 48, 64, 128, 256, 512):
        d = hicolor / f"{sz}x{sz}" / "apps"
        d.mkdir(parents=True, exist_ok=True)
        for theme_name, file_stem in app_icons.items():
            src = OUT / f"{file_stem}-{sz}.png"
            if not src.exists() and file_stem == "gltd-notes":
                src = OUT / f"gltd-notes-{sz}.png"
            if src.exists():
                (d / f"{theme_name}.png").write_bytes(src.read_bytes())
    print(f"Icons in {OUT}")


if __name__ == "__main__":
    save_all()
