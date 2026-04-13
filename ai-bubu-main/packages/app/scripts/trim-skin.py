#!/usr/bin/env python3
"""
Trim whitespace from sprite sheet images in a skin directory.

Analyzes all frames across all animation images in a skin, finds the global
content bounding box (both vertical and horizontal), and crops all images.
Updates skin.json accordingly.

Usage:
    python3 scripts/trim-skin.py public/skins/otter
    python3 scripts/trim-skin.py public/skins/line --padding 6
    python3 scripts/trim-skin.py public/skins/otter --dry-run
    python3 scripts/trim-skin.py public/skins/line --vertical-only
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def find_frame_bounds(img_path: Path, frame_w: int, frame_h: int):
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    cols = w // frame_w
    rows = h // frame_h
    v_bounds = []
    h_bounds = []
    for r in range(rows):
        for c in range(cols):
            frame = np.array(img.crop((c * frame_w, r * frame_h, (c + 1) * frame_w, (r + 1) * frame_h)))
            alpha = frame[:, :, 3]
            ys = np.where(alpha.max(axis=1) > 0)[0]
            xs = np.where(alpha.max(axis=0) > 0)[0]
            if len(ys) > 0:
                v_bounds.append((int(ys[0]), int(ys[-1])))
            if len(xs) > 0:
                h_bounds.append((int(xs[0]), int(xs[-1])))
    return v_bounds, h_bounds


def crop_sprite_sheet(img_path: Path, frame_w: int, frame_h: int,
                      crop_top: int, crop_bottom: int,
                      crop_left: int, crop_right: int):
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    cols = w // frame_w
    rows = h // frame_h

    new_fw = crop_right - crop_left + 1
    new_fh = crop_bottom - crop_top + 1
    result = Image.new("RGBA", (cols * new_fw, rows * new_fh), (0, 0, 0, 0))

    for r in range(rows):
        for c in range(cols):
            frame = img.crop((
                c * frame_w + crop_left, r * frame_h + crop_top,
                c * frame_w + crop_right + 1, r * frame_h + crop_bottom + 1,
            ))
            result.paste(frame, (c * new_fw, r * new_fh))

    return result, new_fw, new_fh


def main():
    parser = argparse.ArgumentParser(description="Trim whitespace from skin sprites")
    parser.add_argument("skin_dir", help="Path to skin directory")
    parser.add_argument("--padding", type=int, default=4, help="Padding pixels (default: 4)")
    parser.add_argument("--dry-run", action="store_true", help="Only analyze, don't modify")
    parser.add_argument("--vertical-only", action="store_true", help="Only trim vertically")
    args = parser.parse_args()

    skin_dir = Path(args.skin_dir)
    skin_json_path = skin_dir / "skin.json"

    if not skin_json_path.exists():
        print(f"Error: {skin_json_path} not found")
        sys.exit(1)

    with open(skin_json_path) as f:
        skin = json.load(f)

    animations = skin.get("animations", {})
    if not animations:
        print("Error: no animations found in skin.json")
        sys.exit(1)

    file_configs: dict[str, dict] = {}
    for state, anim in animations.items():
        sprite = anim.get("sprite", {})
        fname = anim.get("file", "skin.png")
        fw = sprite.get("frameWidth", 128)
        fh = sprite.get("frameHeight", 128)
        if fname not in file_configs:
            file_configs[fname] = {"frameWidth": fw, "frameHeight": fh, "states": []}
        file_configs[fname]["states"].append(state)

    global_top = None
    global_bottom = None
    global_left = None
    global_right = None
    original_fw = None
    original_fh = None

    for fname, cfg in file_configs.items():
        img_path = skin_dir / fname
        if not img_path.exists():
            print(f"Warning: {img_path} not found, skipping")
            continue

        fw, fh = cfg["frameWidth"], cfg["frameHeight"]
        original_fw = fw
        original_fh = fh
        v_bounds, h_bounds = find_frame_bounds(img_path, fw, fh)

        if not v_bounds:
            print(f"Warning: {fname} has no visible content")
            continue

        file_top = min(b[0] for b in v_bounds)
        file_bot = max(b[1] for b in v_bounds)
        file_left = min(b[0] for b in h_bounds)
        file_right = max(b[1] for b in h_bounds)

        print(f"  {fname}: {len(v_bounds)} frames, rows {file_top}-{file_bot}/{fh}, cols {file_left}-{file_right}/{fw}")

        if global_top is None:
            global_top, global_bottom = file_top, file_bot
            global_left, global_right = file_left, file_right
        else:
            global_top = min(global_top, file_top)
            global_bottom = max(global_bottom, file_bot)
            global_left = min(global_left, file_left)
            global_right = max(global_right, file_right)

    if global_top is None:
        print("No content found")
        sys.exit(1)

    crop_top = max(0, global_top - args.padding)
    crop_bottom = min(original_fh - 1, global_bottom + args.padding)
    new_fh = crop_bottom - crop_top + 1

    if args.vertical_only:
        crop_left, crop_right, new_fw = 0, original_fw - 1, original_fw
    else:
        crop_left = max(0, global_left - args.padding)
        crop_right = min(original_fw - 1, global_right + args.padding)
        new_fw = crop_right - crop_left + 1

    print(f"\n  Vertical: rows {global_top}-{global_bottom} → crop {crop_top}-{crop_bottom} (h: {original_fh} → {new_fh})")
    if not args.vertical_only:
        print(f"  Horizontal: cols {global_left}-{global_right} → crop {crop_left}-{crop_right} (w: {original_fw} → {new_fw})")
    total_before = original_fw * original_fh
    total_after = new_fw * new_fh
    print(f"  Frame: {original_fw}x{original_fh} → {new_fw}x{new_fh} ({(total_before - total_after) / total_before * 100:.0f}% reduction)")

    if args.dry_run:
        print("\n  [DRY RUN] No files modified.")
        return

    for fname, cfg in file_configs.items():
        img_path = skin_dir / fname
        if not img_path.exists():
            continue

        fw, fh = cfg["frameWidth"], cfg["frameHeight"]
        cropped, _, _ = crop_sprite_sheet(img_path, fw, fh, crop_top, crop_bottom, crop_left, crop_right)
        cropped.save(img_path)
        print(f"  Saved: {img_path} → {cropped.size[0]}x{cropped.size[1]}")

    for state, anim in animations.items():
        sprite = anim.get("sprite", {})
        sprite["frameWidth"] = int(new_fw)
        sprite["frameHeight"] = int(new_fh)

        fname = anim.get("file", "skin.png")
        img_path = skin_dir / fname
        if img_path.exists():
            img = Image.open(img_path)
            sprite["columns"] = int(img.size[0] // new_fw)

    old_w, old_h = skin["size"]["width"], skin["size"]["height"]
    w_scale = old_w / original_fw
    h_scale = old_h / original_fh
    skin["size"]["width"] = int(max(1, round(new_fw * w_scale)))
    skin["size"]["height"] = int(max(1, round(new_fh * h_scale)))

    with open(skin_json_path, "w") as f:
        json.dump(skin, f, indent=2, ensure_ascii=False)
    print(f"  Updated: {skin_json_path} (size: {old_w}x{old_h} → {skin['size']['width']}x{skin['size']['height']})")

    print("\n  Done!")


if __name__ == "__main__":
    main()
