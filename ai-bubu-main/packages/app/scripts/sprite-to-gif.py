#!/usr/bin/env python3
"""将雪碧图按 skin.json 配置转换为 GIF 动画。

用法:
    python scripts/sprite-to-gif.py public/skins/vita
    python scripts/sprite-to-gif.py public/skins/vita --scale 8
    python scripts/sprite-to-gif.py public/skins/vita --animation idle
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("需要 Pillow 库，请运行: pip install Pillow")
    sys.exit(1)


def extract_frames(sheet: Image.Image, sprite_cfg: dict) -> list[Image.Image]:
    fw = sprite_cfg["frameWidth"]
    fh = sprite_cfg["frameHeight"]
    cols = sprite_cfg["columns"]
    start = sprite_cfg.get("startFrame", 0)
    count = sprite_cfg["frameCount"]

    frames = []
    for i in range(start, start + count):
        col = i % cols
        row = i // cols
        box = (col * fw, row * fh, (col + 1) * fw, (row + 1) * fh)
        frames.append(sheet.crop(box))
    return frames


def scale_frames(frames: list[Image.Image], factor: int) -> list[Image.Image]:
    if factor <= 1:
        return frames
    return [
        f.resize((f.width * factor, f.height * factor), Image.NEAREST)
        for f in frames
    ]


def save_gif(frames: list[Image.Image], path: Path, fps: int):
    duration = max(1, round(1000 / fps))
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=0,
        disposal=2,
        transparency=0,
    )
    print(f"  ✅ {path.name}  ({len(frames)} 帧, {fps}fps, {duration}ms/帧)")


def main():
    parser = argparse.ArgumentParser(description="雪碧图 → GIF 转换器")
    parser.add_argument("skin_dir", help="皮肤目录路径，如 public/skins/vita")
    parser.add_argument("--scale", type=int, default=4, help="放大倍数 (默认 4)")
    parser.add_argument("--animation", help="只导出指定动画，不指定则导出全部")
    args = parser.parse_args()

    skin_dir = Path(args.skin_dir)
    config_path = skin_dir / "skin.json"
    if not config_path.exists():
        print(f"❌ 找不到 {config_path}")
        sys.exit(1)

    config = json.loads(config_path.read_text())
    animations = config.get("animations", {})

    if args.animation:
        if args.animation not in animations:
            print(f"❌ 动画 '{args.animation}' 不存在，可用: {', '.join(animations)}")
            sys.exit(1)
        animations = {args.animation: animations[args.animation]}

    sheets: dict[str, Image.Image] = {}
    print(f"🎨 {config.get('name', skin_dir.name)}  (scale={args.scale}x)\n")

    for anim_name, anim_cfg in animations.items():
        file_name = anim_cfg["file"]
        if file_name not in sheets:
            img_path = skin_dir / file_name
            if not img_path.exists():
                print(f"  ⚠️  跳过 {anim_name}: 找不到 {img_path}")
                continue
            sheets[file_name] = Image.open(img_path).convert("RGBA")

        sheet = sheets[file_name]
        sprite = anim_cfg["sprite"]
        fps = sprite.get("fps", 6)

        frames = extract_frames(sheet, sprite)
        frames = scale_frames(frames, args.scale)
        out_path = skin_dir / f"{anim_name}.gif"
        save_gif(frames, out_path, fps)

    print("\n🎉 完成!")


if __name__ == "__main__":
    main()
