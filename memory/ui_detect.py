#!/usr/bin/env python3
"""
UI元素检测 - 基于OmniParser YOLO + RapidOCR
用法:
  from ui_detect import detect
  elements = detect("screenshot.png", mode='crop')  # 或 'match'
返回: [{'bbox':[x1,y1,x2,y2], 'type':'icon'|'text', 'label':str|None, 'confidence':float}]
模式: crop=YOLO+逐块OCR(label全) | match=YOLO+全图OCR空间匹配(快,label=None可VLM保底)
依赖: ultralytics, rapidocr-onnxruntime, pillow, numpy
"""
from pathlib import Path
from ultralytics import YOLO
from PIL import Image, ImageDraw
import numpy as np

DEFAULT_MODEL = str(Path(__file__).resolve().parent.parent / 'temp' / 'weights' / 'icon_detect' / 'model.pt')

try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr = RapidOCR()
except ImportError:
    _ocr = None

def _yolo(image_path, model_path=None, conf=0.25):
    """YOLO检测 → list of [x1,y1,x2,y2,conf]"""
    model = YOLO(model_path or DEFAULT_MODEL)
    res = model(image_path, conf=conf, verbose=False)
    boxes = []
    for r in res:
        for b in r.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0].cpu().numpy())
            boxes.append([x1, y1, x2, y2, float(b.conf[0])])
    return boxes

def _ocr_full(image_path):
    """全图OCR → list of [x1,y1,x2,y2,text,conf]"""
    if not _ocr: return []
    result, _ = _ocr(image_path)
    if not result: return []
    out = []
    for bbox, text, conf in result:
        xs = [p[0] for p in bbox]; ys = [p[1] for p in bbox]
        out.append([int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), text, conf])
    return out

def _ocr_crop(img, bbox):
    """裁剪区域OCR → text or None"""
    if not _ocr: return None
    x1, y1, x2, y2 = bbox
    crop = img.crop((x1, y1, x2, y2))
    arr = np.array(crop)
    result, _ = _ocr(arr)
    if not result: return None
    return ' '.join(t for _, t, _ in result)

def _iou(a, b):
    """计算两个bbox的交集占b面积的比例(包含率)"""
    x1, y1, x2, y2 = max(a[0],b[0]), max(a[1],b[1]), min(a[2],b[2]), min(a[3],b[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    area_b = (b[2]-b[0]) * (b[3]-b[1])
    return inter / area_b if area_b > 0 else 0

def detect(image_path, mode='crop', model_path=None, conf=0.25, iou_thresh=0.5):
    """
    统一检测入口，返回元素列表:
    [{'bbox':[x1,y1,x2,y2], 'type':'icon'|'text', 'label':str|None, 'confidence':float}]
    mode: 'crop' = YOLO+逐块OCR | 'match' = YOLO+全图OCR空间匹配
    支持 image_path: str 路径 或 PIL.Image 对象
    """
    # 归一化：PIL Image → 临时文件
    if isinstance(image_path, Image.Image):
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        image_path.save(tmp.name)
        image_path = tmp.name
    img = Image.open(image_path)

    yolo_boxes = _yolo(image_path, model_path, conf)
    elements = []

    if mode == 'crop':
        # YOLO元素逐块OCR
        for x1, y1, x2, y2, c in yolo_boxes:
            label = _ocr_crop(img, [x1, y1, x2, y2])
            elements.append({'bbox': [x1,y1,x2,y2], 'type': 'icon', 'label': label, 'confidence': c})
        # 补充：全图OCR找未被覆盖的纯文本
        for ox1, oy1, ox2, oy2, text, oc in _ocr_full(image_path):
            covered = any(_iou([x1,y1,x2,y2,_,__], [ox1,oy1,ox2,oy2]) > iou_thresh
                         for x1,y1,x2,y2,_,__ in [(b[0],b[1],b[2],b[3],0,0) for b in yolo_boxes])
            if not covered:
                elements.append({'bbox': [ox1,oy1,ox2,oy2], 'type': 'text', 'label': text, 'confidence': oc})

    elif mode == 'match':
        ocr_items = _ocr_full(image_path)
        matched_ocr = set()
        for x1, y1, x2, y2, c in yolo_boxes:
            label = None
            for i, (ox1, oy1, ox2, oy2, text, oc) in enumerate(ocr_items):
                if _iou([x1,y1,x2,y2], [ox1,oy1,ox2,oy2]) > iou_thresh:
                    label = text; matched_ocr.add(i); break
            elements.append({'bbox': [x1,y1,x2,y2], 'type': 'icon', 'label': label, 'confidence': c})
        # 未匹配的OCR作为独立text元素
        for i, (ox1, oy1, ox2, oy2, text, oc) in enumerate(ocr_items):
            if i not in matched_ocr:
                elements.append({'bbox': [ox1,oy1,ox2,oy2], 'type': 'text', 'label': text, 'confidence': oc})

    return elements

def visualize(image_path, elements, output_path=None):
    """调试用: 可视化元素列表"""
    from PIL import ImageFont
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("msyh.ttc", 14)
    except:
        font = ImageFont.load_default()
    for el in elements:
        x1, y1, x2, y2 = el['bbox']
        color = 'red' if el['type'] == 'icon' else 'blue'
        draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
        tag = el.get('label') or f"{el['confidence']:.2f}"
        draw.text((x1, y1-16), tag[:15], fill=color, font=font)
    if output_path: img.save(output_path)
    return img


