#!/usr/bin/env python3
"""Generate pet.png avatar for each skin by extracting the first idle frame."""

import json
import shutil
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SKINS_DIR = ROOT / "public" / "skins"
AVATAR_SIZE = 96


def process_skin(skin_dir: Path):
    skin_json = skin_dir / "skin.json"
    if not skin_json.exists():
        return

    pet_gif = skin_dir / "pet.gif"
    pet_png = skin_dir / "pet.png"

    if pet_gif.exists() or pet_png.exists():
        print(f"  {skin_dir.name}: already has pet avatar, skip")
        return

    with open(skin_json) as f:
        manifest = json.load(f)

    idle = manifest.get("animations", {}).get("idle")
    if not idle:
        first_key = next(iter(manifest.get("animations", {})), None)
        if first_key:
            idle = manifest["animations"][first_key]

    if not idle:
        print(f"  {skin_dir.name}: no animations, skip")
        return

    sprite_file = skin_dir / idle["file"]
    if not sprite_file.exists():
        print(f"  {skin_dir.name}: sprite file not found: {idle['file']}")
        return

    sprite = idle.get("sprite")
    if not sprite:
        img = Image.open(sprite_file).convert("RGBA")
        img = img.resize((AVATAR_SIZE, AVATAR_SIZE), Image.NEAREST)
        img.save(str(pet_png), format="PNG")
        print(f"  {skin_dir.name}: pet.png (from full image)")
        return

    fw = sprite["frameWidth"]
    fh = sprite["frameHeight"]
    start = sprite.get("startFrame", 0)
    cols = sprite["columns"]

    col = start % cols
    row = start // cols

    sheet = Image.open(sprite_file).convert("RGBA")
    frame = sheet.crop((col * fw, row * fh, col * fw + fw, row * fh + fh))

    scale = max(1, AVATAR_SIZE // max(fw, fh))
    avatar = frame.resize((fw * scale, fh * scale), Image.NEAREST)

    avatar.save(str(pet_png), format="PNG")
    print(f"  {skin_dir.name}: pet.png ({fw * scale}x{fh * scale})")


def main():
    print("Generating pet avatars...")
    for skin_dir in sorted(SKINS_DIR.iterdir()):
        if skin_dir.is_dir() and (skin_dir / "skin.json").exists():
            process_skin(skin_dir)
    print("Done!")


if __name__ == "__main__":
    main()
