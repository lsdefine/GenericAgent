#!/usr/bin/env python3
"""Simple test to verify desktop pet displays correctly"""
import tkinter as tk
from PIL import Image, ImageTk
import sys
import os

print("=" * 60)
print("Desktop Pet Display Test")
print("=" * 60)

# Load skin config
import json
skin_path = 'frontends/skins/vita'
with open(os.path.join(skin_path, 'skin.json')) as f:
    config = json.load(f)

print(f"\nSkin: {config['name']}")
print(f"Display size: {config['size']['width']}x{config['size']['height']}")

# Create window
root = tk.Tk()
root.title("Pet Test")
root.overrideredirect(True)
root.wm_attributes('-topmost', True)

if sys.platform == 'darwin':
    root.wm_attributes('-transparent', True)
    root.config(bg='systemTransparent')
    bg_color = 'systemTransparent'
else:
    root.wm_attributes('-transparentcolor', '#01FF01')
    root.config(bg='#01FF01')
    bg_color = '#01FF01'

root.geometry('+300+300')

# Load first frame
anim_config = config['animations']['idle']
sprite_config = anim_config['sprite']

img_path = os.path.join(skin_path, anim_config['file'])
img = Image.open(img_path)

# Extract and scale frame
frame_width = sprite_config['frameWidth']
frame_height = sprite_config['frameHeight']
frame = img.crop((0, 0, frame_width, frame_height))

display_width = config['size']['width']
display_height = config['size']['height']
scaled = frame.resize((display_width, display_height), Image.NEAREST)

if scaled.mode != 'RGBA':
    scaled = scaled.convert('RGBA')

photo = ImageTk.PhotoImage(scaled)

label = tk.Label(root, image=photo, bg=bg_color, bd=0)
label.pack()

# Add close button
label.bind('<Double-1>', lambda e: root.destroy())

print(f"\n✓ Window created at (300, 300)")
print(f"✓ Image size: {scaled.size}")
print(f"\nDouble-click the pet to close")
print("=" * 60)

root.mainloop()
