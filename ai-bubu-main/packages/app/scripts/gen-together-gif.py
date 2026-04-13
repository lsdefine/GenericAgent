"""Generate a GIF of two pets running together: Vita in front (larger), Tard behind (smaller)."""
from PIL import Image
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

vita_sheet = Image.open(os.path.join(BASE, 'public/skins/vita/skin.png')).convert('RGBA')
tard_sheet = Image.open(os.path.join(BASE, 'public/skins/tard/skin.png')).convert('RGBA')

def extract_frames(sheet, fw, fh, start, count, cols):
    frames = []
    for i in range(count):
        idx = start + i
        col = idx % cols
        row = idx // cols
        frame = sheet.crop((col * fw, row * fh, col * fw + fw, row * fh + fh))
        frames.append(frame)
    return frames

def get_content_bbox(frames):
    min_x, min_y = 9999, 9999
    max_x, max_y = 0, 0
    for f in frames:
        bb = f.getbbox()
        if bb:
            min_x = min(min_x, bb[0])
            min_y = min(min_y, bb[1])
            max_x = max(max_x, bb[2])
            max_y = max(max_y, bb[3])
    return (min_x, min_y, max_x, max_y)

# Run animations (both 24x24, 8 frames)
vita_run = extract_frames(vita_sheet, 24, 24, 6, 8, 24)
tard_run = extract_frames(tard_sheet, 24, 24, 6, 8, 24)

# Trim transparent padding
vita_bbox = get_content_bbox(vita_run)
vita_cropped = [f.crop(vita_bbox) for f in vita_run]
vc_w, vc_h = vita_cropped[0].size

tard_bbox = get_content_bbox(tard_run)
tard_cropped = [f.crop(tard_bbox) for f in tard_run]
tc_w, tc_h = tard_cropped[0].size

print(f"Vita cropped: {vc_w}x{vc_h}, Tard cropped: {tc_w}x{tc_h}")

# Integer pixel-art scaling
VITA_SCALE = 5
TARD_SCALE = 4

vita_sw = vc_w * VITA_SCALE
vita_sh = vc_h * VITA_SCALE
tard_sw = tc_w * TARD_SCALE
tard_sh = tc_h * TARD_SCALE

print(f"Vita scaled: {vita_sw}x{vita_sh}, Tard scaled: {tard_sw}x{tard_sh}")

GAP = 6
PAD_X = 10
PAD_Y = 10
CANVAS_W = tard_sw + GAP + vita_sw + PAD_X * 2
CANVAS_H = max(vita_sh, tard_sh) + PAD_Y * 2
BG = (255, 255, 255, 255)
GROUND_Y = CANVAS_H - PAD_Y

NUM_FRAMES = 24
FPS = 10

gif_frames = []
for i in range(NUM_FRAMES):
    canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), BG)

    # Tard behind (left, smaller)
    tf = tard_cropped[i % len(tard_cropped)].resize((tard_sw, tard_sh), Image.NEAREST)
    tard_x = PAD_X
    tard_y = GROUND_Y - tard_sh
    canvas.paste(tf, (tard_x, tard_y), tf)

    # Vita in front (right, larger)
    vf = vita_cropped[i % len(vita_cropped)].resize((vita_sw, vita_sh), Image.NEAREST)
    vita_x = tard_x + tard_sw + GAP
    vita_y = GROUND_Y - vita_sh
    canvas.paste(vf, (vita_x, vita_y), vf)

    gif_frames.append(canvas)

out = os.path.join(BASE, 'site/public/pet/together.gif')
os.makedirs(os.path.dirname(out), exist_ok=True)

rgb_frames = []
for f in gif_frames:
    bg = Image.new('RGBA', f.size, BG)
    bg.paste(f, (0, 0), f)
    rgb_frames.append(bg.convert('RGB'))

rgb_frames[0].save(
    out,
    save_all=True,
    append_images=rgb_frames[1:],
    duration=1000 // FPS,
    loop=0,
    optimize=True,
)
print(f"Saved to {out} ({CANVAS_W}x{CANVAS_H}, {NUM_FRAMES} frames, {FPS}fps)")
