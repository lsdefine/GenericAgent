#!/usr/bin/env python3
"""Generate app icons: Vita character on brand gradient background with footprints."""

import struct
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "src-tauri" / "icons"
SITE_DIR = ROOT.parent / "site" / "public"
SKIN_PATH = ROOT / "public" / "skins" / "vita" / "skin.png"

FRAME_W, FRAME_H = 24, 24
IDLE_START_FRAME = 0
COLUMNS = 24

GRAD_TOP = (249, 249, 249)     # #f9f9f9
GRAD_BOTTOM = (249, 249, 249)  # #f9f9f9
CORNER_RADIUS_RATIO = 0.22


def extract_frame(sprite_path: Path, frame_idx: int) -> Image.Image:
    sheet = Image.open(sprite_path).convert("RGBA")
    col = frame_idx % COLUMNS
    row = frame_idx // COLUMNS
    x = col * FRAME_W
    y = row * FRAME_H
    return sheet.crop((x, y, x + FRAME_W, y + FRAME_H))


def make_gradient(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(GRAD_TOP[0] + (GRAD_BOTTOM[0] - GRAD_TOP[0]) * t)
        g = int(GRAD_TOP[1] + (GRAD_BOTTOM[1] - GRAD_TOP[1]) * t)
        b = int(GRAD_TOP[2] + (GRAD_BOTTOM[2] - GRAD_TOP[2]) * t)
        for x in range(size):
            img.putpixel((x, y), (r, g, b, 255))
    return img


def round_corners(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=radius, fill=255)
    img.putalpha(mask)
    return img


def draw_footprints(draw: ImageDraw.ImageDraw, size: int):
    """Draw recognizable footprints: oval pad + two toe dots."""
    base_y = int(size * 0.72)
    pad_w = max(3, int(size * 0.035))
    pad_h = max(2, int(size * 0.025))
    toe_r = max(1, int(size * 0.012))
    toe_gap = max(2, int(size * 0.025))
    toe_up = max(2, int(size * 0.035))

    prints = [
        (0.30, 0.00, 0.45),
        (0.44, 0.04, 0.65),
        (0.58, 0.02, 0.55),
        (0.72, 0.05, 0.40),
    ]
    for rel_x, rel_dy, alpha in prints:
        cx = int(rel_x * size)
        cy = base_y + int(rel_dy * size)
        a = int(255 * alpha)
        color = (255, 255, 255, a)
        draw.ellipse([cx - pad_w, cy - pad_h, cx + pad_w, cy + pad_h], fill=color)
        draw.ellipse([cx - toe_gap - toe_r, cy - toe_up - toe_r, cx - toe_gap + toe_r, cy - toe_up + toe_r], fill=color)
        draw.ellipse([cx + toe_gap - toe_r, cy - toe_up - toe_r, cx + toe_gap + toe_r, cy - toe_up + toe_r], fill=color)


def generate_icon(size: int) -> Image.Image:
    bg = make_gradient(size)
    radius = int(size * CORNER_RADIUS_RATIO)
    bg = round_corners(bg, radius)

    char_frame = extract_frame(SKIN_PATH, IDLE_START_FRAME)

    scale = int(size * 0.75 / FRAME_W)
    scale = max(scale, 1)
    char_scaled = char_frame.resize(
        (FRAME_W * scale, FRAME_H * scale),
        Image.NEAREST,
    )

    cx = (size - char_scaled.width) // 2
    cy = (size - char_scaled.height) // 2
    bg.paste(char_scaled, (cx, cy), char_scaled)

    return bg


def create_ico(images: dict[int, Image.Image], out_path: Path):
    sizes_needed = [16, 32, 48, 128, 256]
    imgs = []
    for s in sizes_needed:
        if s in images:
            imgs.append(images[s])
        else:
            largest = images[max(images.keys())]
            imgs.append(largest.resize((s, s), Image.LANCZOS))
    imgs[0].save(
        str(out_path), format="ICO",
        sizes=[(im.width, im.height) for im in imgs],
        append_images=imgs[1:],
    )


def create_icns(img_512: Image.Image, out_path: Path):
    img_256 = img_512.resize((256, 256), Image.LANCZOS)
    buf_256 = io.BytesIO()
    img_256.save(buf_256, format="PNG")
    data_256 = buf_256.getvalue()

    buf_512 = io.BytesIO()
    img_512.save(buf_512, format="PNG")
    data_512 = buf_512.getvalue()

    entries = [(b"ic08", data_256), (b"ic09", data_512)]
    total = 8 + sum(8 + len(d) for _, d in entries)

    with open(out_path, "wb") as f:
        f.write(b"icns")
        f.write(struct.pack(">I", total))
        for t, d in entries:
            f.write(t)
            f.write(struct.pack(">I", 8 + len(d)))
            f.write(d)


def generate_favicon_svg(size: int = 32) -> str:
    """Generate an SVG favicon with gradient background and the character hint."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#f9f9f9"/>
      <stop offset="100%" stop-color="#f9f9f9"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="{int(size * 0.22)}" fill="url(#bg)"/>
  <text x="{size // 2}" y="{int(size * 0.62)}" text-anchor="middle"
        fill="white" font-size="{int(size * 0.45)}" font-weight="bold"
        font-family="sans-serif">步</text>
</svg>'''


def main():
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    targets = {
        32: "32x32.png",
        128: "128x128.png",
        256: "128x128@2x.png",
        512: "icon.png",
    }

    images: dict[int, Image.Image] = {}
    for size, name in targets.items():
        img = generate_icon(size)
        images[size] = img
        out = ICONS_DIR / name
        img.save(str(out), format="PNG")
        print(f"  {name} ({size}x{size})")

    for extra_s in [16, 48]:
        images[extra_s] = generate_icon(extra_s)

    create_ico(images, ICONS_DIR / "icon.ico")
    print("  icon.ico")

    create_icns(images[512], ICONS_DIR / "icon.icns")
    print("  icon.icns")

    svg_content = generate_favicon_svg()
    (SITE_DIR / "favicon.svg").write_text(svg_content)
    print("  site/public/favicon.svg")

    print("\nDone!")


if __name__ == "__main__":
    main()
