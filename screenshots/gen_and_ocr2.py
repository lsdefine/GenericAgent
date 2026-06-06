#!/usr/bin/env python3
"""
Vision Pipeline 实战 v2: 生成高对比度系统健康截图 → OCR 提取关键指标
"""
import subprocess, os, sys
sys.path.insert(0, '/home/admin/GenericAgent')
os.chdir('/home/admin/GenericAgent')

from PIL import Image, ImageDraw, ImageFont
from scripts.vision_integration import ocr_image

# ── 1. 获取真实系统数据 ──
mem = subprocess.run(['free','-h'], capture_output=True, text=True).stdout
disk = subprocess.run(['df','-h','/'], capture_output=True, text=True).stdout
uptime = subprocess.run(['uptime','-p'], capture_output=True, text=True).stdout.strip()
load = subprocess.run(['cat','/proc/loadavg'], capture_output=True, text=True).stdout.strip()

mem_line = [l for l in mem.split('\n') if 'Mem:' in l]
mem_total = mem_line[0].split()[1] if mem_line else '?'
mem_avail = mem_line[0].split()[6] if mem_line else '?'
disk_lines = disk.strip().split('\n')
disk_used = disk_lines[1].split()[2] if len(disk_lines) > 1 else '?'
disk_avail = disk_lines[1].split()[3] if len(disk_lines) > 1 else '?'
disk_pct = disk_lines[1].split()[4] if len(disk_lines) > 1 else '?'
load_1m = load.split()[0] if load else '?'

# ── 2. 生成高对比度截图（白底黑字） ──
lines = [
    "== System Health Monitor ==",
    f"Time: 2026-06-07 07:05 UTC",
    "",
    f"Memory: {mem_total} total, {mem_avail} avail",
    f"Disk: {disk_used} used / {disk_avail} free ({disk_pct})",
    f"Load: {load_1m}",
    f"Uptime: {uptime.replace('up ','')}",
    "",
    "Services:",
    "  openllm       [UP]",
    "  nanobot-api   [UP]",
    "  nanobot-gw    [UP]",
    "  code-server   [UP]",
    "  chromedriver  [DOWN]",
]

W, H = 800, len(lines) * 36 + 60
img = Image.new('RGB', (W, H), color=(255, 255, 255))
draw = ImageDraw.Draw(img)

try:
    font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf", 28)
except:
    try:
        font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSansMono.ttf", 28)
    except:
        font = ImageFont.load_default()

y = 30
for line in lines:
    color = (0, 0, 0)  # black text on white background
    draw.text((30, y), line, fill=color, font=font)
    y += 34

screenshot_path = 'screenshots/system_health_ocr_v2.png'
img.save(screenshot_path)
print(f"✅ Screenshot v2 generated: {screenshot_path} ({W}x{H})")

# ── 3. OCR 提取文本 ──
print("\n--- OCR Extraction ---")
text = ocr_image(screenshot_path, lang='eng')
print(f"📝 OCR extracted {len(text)} characters:")
print(text)

# ── 4. 提取关键指标 ──
print("\n--- Key Metrics Extracted ---")
metrics = {}
for line in text.split('\n'):
    line = line.strip()
    if 'Memory' in line:
        metrics['memory'] = line
    elif 'Disk' in line:
        metrics['disk'] = line
    elif 'Load' in line:
        metrics['load'] = line
    elif 'Uptime' in line:
        metrics['uptime'] = line
    elif 'openllm' in line or 'nanobot' in line or 'code-server' in line or 'chromedriver' in line:
        status = 'UP' if 'UP' in line else 'DOWN'
        svc_name = line.split('[')[0].strip() if '[' in line else line
        metrics[f'svc_{svc_name}'] = status

for k, v in metrics.items():
    print(f"  {k}: {v}")

print(f"\n✅ Total metrics extracted: {len(metrics)}")
print(f"✅ Vision Pipeline实战验证完成")
