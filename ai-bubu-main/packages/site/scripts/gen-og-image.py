#!/usr/bin/env python3
"""Generate OG image (1200x630) from existing assets."""

from PIL import Image, ImageDraw, ImageFont
import os

SITE_DIR = os.path.join(os.path.dirname(__file__), '..', 'public')
OUT = os.path.join(SITE_DIR, 'og-image.png')

W, H = 1200, 630

BG_COLOR = (99, 102, 241)
BG_DARK  = (67, 56, 202)
TEXT_W   = (255, 255, 255)
TEXT_SUB = (199, 199, 255)

img = Image.new('RGBA', (W, H), BG_COLOR)
draw = ImageDraw.Draw(img)

for y in range(H):
    t = y / H
    r = int(BG_COLOR[0] + (BG_DARK[0] - BG_COLOR[0]) * t)
    g = int(BG_COLOR[1] + (BG_DARK[1] - BG_COLOR[1]) * t)
    b = int(BG_COLOR[2] + (BG_DARK[2] - BG_COLOR[2]) * t)
    draw.line([(0, y), (W, y)], fill=(r, g, b))

# Load fonts
def load_font(size, chinese=False):
    if chinese:
        for path in ["/System/Library/Fonts/PingFang.ttc",
                     "/System/Library/Fonts/STHeiti Light.ttc",
                     "/System/Library/Fonts/Hiragino Sans GB.ttc"]:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
    for path in ["/System/Library/Fonts/HelveticaNeue.ttc",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/System/Library/Fonts/SFNSDisplay.ttf",
                 "/System/Library/Fonts/Arial.ttf"]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

font_title = load_font(96)
font_zh    = load_font(42, chinese=True)
font_sub   = load_font(36)
font_tools = load_font(26)
font_url   = load_font(24)

favicon_path = os.path.join(SITE_DIR, 'favicon.png')
favicon = Image.open(favicon_path).convert('RGBA')
pet_size = 320
favicon_scaled = favicon.resize((pet_size, pet_size), Image.NEAREST)

pet_x = W - pet_size - 100
pet_y = (H - pet_size) // 2 - 30
img.paste(favicon_scaled, (pet_x, pet_y), favicon_scaled)

# Load 4 skin sprites and place at bottom
skin_names = ['doux.png', 'vita.png', 'mort.png', 'tard.png']
sprite_size = 48
sprite_y = H - sprite_size - 40
sprite_start_x = W - 100 - (len(skin_names) * (sprite_size + 16))
for i, name in enumerate(skin_names):
    skin_path = os.path.join(SITE_DIR, 'skins', name)
    skin = Image.open(skin_path).convert('RGBA')
    frame_w = skin.width // 24
    frame_h = skin.height
    frame = skin.crop((0, 0, frame_w, frame_h))
    frame_scaled = frame.resize((sprite_size, sprite_size), Image.NEAREST)
    sx = sprite_start_x + i * (sprite_size + 16)
    img.paste(frame_scaled, (sx, sprite_y), frame_scaled)

left = 80

draw.text((left, 120), "AIbubu", fill=TEXT_W, font=font_title)

draw.text((left, 240), "AI 步步  —  AI 时代的编码计步器", fill=TEXT_SUB, font=font_zh)

draw.line([(left, 310), (left + 80, 310)], fill=(255, 255, 255, 180), width=3)

draw.text((left, 340), "A Coding Step Counter", fill=TEXT_W, font=font_sub)
draw.text((left, 390), "for the AI Era", fill=TEXT_W, font=font_sub)

draw.text((left, 470), "Cursor · Claude Code · Codex · Trae · OpenCode & more", fill=TEXT_SUB, font=font_tools)

# Bottom bar
draw.rectangle([(0, H - 4), (W, H)], fill=(255, 255, 255, 40))
draw.text((left, H - 55), "aibubu.app  ·  Free & Open Source", fill=TEXT_SUB, font=font_url)

img = img.convert('RGB')
img.save(OUT, 'PNG', optimize=True)
print(f"OG image saved: {OUT}")
print(f"Dimensions: {W}x{H}, Size: {os.path.getsize(OUT)} bytes")
