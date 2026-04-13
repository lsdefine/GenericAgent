#!/usr/bin/env python3
"""
Skin Builder — 将散帧图片合并为精灵图 + skin.json

用法:
  python3 scripts/build-skin.py public/skins/boy/
  python3 scripts/build-skin.py public/skins/boy/ --scale 64
  python3 scripts/build-skin.py public/skins/boy/ --scale 64 --name "Boy" --author "Artist"

目录约定:
  public/skins/{id}/
  ├── idle/       ← 站立帧（必须）
  ├── walk/       ← 散步帧（可选，缺少则复用 idle）
  ├── run/        ← 跑步帧（可选，缺少则复用 walk/idle）
  ├── sprint/     ← 飞跑帧（可选，缺少则复用 run）
  └── (输出)
      ├── skin.png
      └── skin.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: pip3 install Pillow")
    sys.exit(1)

STATES = ["idle", "walk", "run", "sprint"]

FPS_MAP = {
    "idle": 6,
    "walk": 6,
    "run": 10,
    "sprint": 16,
}

FALLBACK_CHAIN = {
    "walk": "idle",
    "run": "walk",
    "sprint": "run",
}


def find_frames(state_dir: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    frames = sorted(
        f for f in state_dir.iterdir()
        if f.is_file() and f.suffix.lower() in exts
    )
    return frames


def resolve_frames(skin_dir: Path) -> dict[str, list[Path]]:
    resolved: dict[str, list[Path]] = {}

    available: dict[str, list[Path]] = {}
    for state in STATES:
        state_dir = skin_dir / state
        if state_dir.is_dir():
            frames = find_frames(state_dir)
            if frames:
                available[state] = frames

    if "idle" not in available:
        print(f"Error: {skin_dir}/idle/ directory is required with at least one frame.")
        sys.exit(1)

    for state in STATES:
        if state in available:
            resolved[state] = available[state]
        else:
            fallback = FALLBACK_CHAIN.get(state)
            while fallback and fallback not in available:
                fallback = FALLBACK_CHAIN.get(fallback)
            source = fallback or "idle"
            resolved[state] = available[source]
            print(f"  {state}: fallback to {source} ({len(available[source])} frames)")

    return resolved


def build_sprite_sheet(
    resolved: dict[str, list[Path]],
    scale_width: int | None,
) -> tuple[Image.Image, int, int, dict[str, tuple[int, int]]]:
    sample = Image.open(resolved["idle"][0])
    orig_w, orig_h = sample.size

    if scale_width and scale_width != orig_w:
        ratio = scale_width / orig_w
        fw = scale_width
        fh = round(orig_h * ratio)
    else:
        fw, fh = orig_w, orig_h

    total_frames = sum(len(frames) for frames in resolved.values())
    sheet = Image.new("RGBA", (fw * total_frames, fh), (0, 0, 0, 0))

    state_info: dict[str, tuple[int, int]] = {}
    col = 0
    for state in STATES:
        frames = resolved[state]
        state_info[state] = (col, len(frames))
        for frame_path in frames:
            img = Image.open(frame_path).convert("RGBA")
            if img.size != (fw, fh):
                img = img.resize((fw, fh), Image.LANCZOS)
            sheet.paste(img, (col * fw, 0))
            col += 1

    return sheet, fw, fh, state_info


def generate_manifest(
    fw: int,
    fh: int,
    total_frames: int,
    state_info: dict[str, tuple[int, int]],
    name: str,
    author: str,
    description: str,
) -> dict:
    animations = {}
    for state in STATES:
        start, count = state_info[state]
        animations[state] = {
            "file": "skin.png",
            "loop": True,
            "sprite": {
                "frameWidth": fw,
                "frameHeight": fh,
                "frameCount": count,
                "columns": total_frames,
                "fps": FPS_MAP[state],
                "startFrame": start,
            },
        }

    return {
        "name": name,
        "version": "1.0.0",
        "author": author,
        "description": description,
        "style": "pixel",
        "format": "sprite",
        "size": {"width": fw, "height": fh},
        "animations": animations,
    }


def main():
    parser = argparse.ArgumentParser(description="Build sprite sheet from frame directories")
    parser.add_argument("skin_dir", help="Path to skin directory (e.g. public/skins/boy/)")
    parser.add_argument("--scale", type=int, default=None, help="Scale frame width (height auto)")
    parser.add_argument("--name", default=None, help="Skin display name")
    parser.add_argument("--author", default="Unknown", help="Author name")
    parser.add_argument("--description", default="", help="Skin description")
    args = parser.parse_args()

    skin_dir = Path(args.skin_dir).resolve()
    if not skin_dir.is_dir():
        print(f"Error: {skin_dir} is not a directory")
        sys.exit(1)

    skin_id = skin_dir.name
    name = args.name or skin_id.capitalize()
    description = args.description or f"{name} 角色皮肤"

    print(f"Building skin: {skin_id}")
    print(f"  Directory: {skin_dir}")

    resolved = resolve_frames(skin_dir)

    for state in STATES:
        print(f"  {state}: {len(resolved[state])} frames")

    sheet, fw, fh, state_info = build_sprite_sheet(resolved, args.scale)
    total_frames = sum(len(f) for f in resolved.values())

    out_png = skin_dir / "skin.png"
    sheet.save(out_png, "PNG", optimize=True)
    size_kb = out_png.stat().st_size / 1024
    print(f"  Output: {out_png} ({sheet.size[0]}x{sheet.size[1]}, {size_kb:.1f} KB)")

    manifest = generate_manifest(fw, fh, total_frames, state_info, name, args.author, description)
    out_json = skin_dir / "skin.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  Output: {out_json}")

    print("Done!")


if __name__ == "__main__":
    main()
