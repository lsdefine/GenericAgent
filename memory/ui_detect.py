#!/usr/bin/env python3
"""
UI元素检测 - YOLO + RapidOCR
用法:
  from ui_detect import detect
  elements = detect("screenshot.png")          # 默认match模式
  elements = detect(pil_image)                 # 支持PIL.Image
  elements = detect(img, mode='crop')          # crop备选
返回: [{'bbox':[x1,y1,x2,y2], 'type':'icon'|'text', 'label':str|None, 'confidence':float}]
模式: match=YOLO+全图OCR IoU匹配(推荐,1.2s,无文字图标label=None可VLM保底) | crop=拼接crop OCR(备选,更精确,2.3s)
依赖: ultralytics, rapidocr-onnxruntime, pillow, numpy
"""
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np
import json, urllib.request, subprocess, sys, time

print('[UI DETECT] 截图分析后必须使用物理坐标，ljqCtrl也使用物理坐标！')

DEFAULT_MODEL = str(Path(__file__).resolve().parent.parent / 'temp' / 'weights' / 'icon_detect' / 'model.pt')

try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr = RapidOCR()
except ImportError: _ocr = None

_YOLO = None
_YOLO_PORT = 31876

def _yolo_local(image_path, conf=0.25):
    global _YOLO
    if _YOLO is None:
        from ultralytics import YOLO
        _YOLO = YOLO(DEFAULT_MODEL)
    res = _YOLO(image_path, conf=conf, verbose=False)
    boxes = []
    for r in res:
        for b in r.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0].cpu().numpy())
            boxes.append([x1, y1, x2, y2, float(b.conf[0])])
    return boxes


def _ping_yolo_daemon():
    try: return urllib.request.urlopen(f'http://127.0.0.1:{_YOLO_PORT}/ping', timeout=0.1).read() == b'ui_detect_yolo'
    except Exception: return False

def _yolo(image_path, conf=0.25):
    """YOLO检测 → list of [x1,y1,x2,y2,conf]；默认模型走跨进程daemon cache，失败回退本地"""
    if not _ping_yolo_daemon():
        kw = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)} if sys.platform == 'win32' else {}
        subprocess.Popen([sys.executable, __file__, '--yolo-daemon'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        for _ in range(15):
            if _ping_yolo_daemon(): break
            time.sleep(0.5)
    try:
        data = json.dumps({'path': str(image_path), 'conf': conf}).encode('utf-8')
        req = urllib.request.Request(f'http://127.0.0.1:{_YOLO_PORT}/yolo', data=data, headers={'Content-Type': 'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=3).read().decode('utf-8'))['boxes']
    except Exception: return _yolo_local(image_path, conf)

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

def _ocr_crops_batch(img, yolo_boxes):
    """批量OCR：将所有YOLO框crop垂直拼接为一张图，一次OCR，按y坐标映射回各box → {box_idx: text}"""
    if not _ocr or not yolo_boxes: return {}
    
    crops, offsets = [], []  # offsets: [(y_off, orig_x1, orig_y1, box_idx)]
    max_w, y_cursor = 0, 0
    for idx, (x1, y1, x2, y2, _) in enumerate(yolo_boxes):
        crop = img.crop((x1, y1, x2, y2))
        w, h = crop.size
        max_w = max(max_w, w)
        crops.append(crop)
        offsets.append((y_cursor, x1, y1, idx))
        y_cursor += h
    if max_w == 0: return {}
    # 垂直拼接
    stitched = Image.new('RGB', (max_w, y_cursor), (255, 255, 255))
    for i, crop in enumerate(crops):
        stitched.paste(crop, (0, offsets[i][0]))
    
    result, _ = _ocr(np.array(stitched))
    if not result: return {}
    # 映射：OCR框中心y → 归属的crop
    labels = {}
    for bbox, text, _ in result:
        cy = sum(p[1] for p in bbox) / len(bbox)
        for y_off, ox1, oy1, idx in offsets:
            h = yolo_boxes[idx][3] - yolo_boxes[idx][1]
            if y_off <= cy < y_off + h:
                old = labels.get(idx)
                labels[idx] = (old + ' ' + text) if old else text
                break
    return labels

def _iou(a, b):
    """计算两个bbox的交集占b面积的比例(包含率)"""
    x1, y1, x2, y2 = max(a[0],b[0]), max(a[1],b[1]), min(a[2],b[2]), min(a[3],b[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    area_b = (b[2]-b[0]) * (b[3]-b[1])
    return inter / area_b if area_b > 0 else 0

def detect(image_path, mode='match', conf=0.25, iou_thresh=0.5):
    """
    统一检测入口，返回元素列表:
    [{'bbox':[x1,y1,x2,y2], 'type':'icon'|'text', 'label':str|None, 'confidence':float}]
    mode: 'match' = YOLO+全图OCR空间匹配(推荐, 快) | 'crop' = YOLO+拼接OCR(备选, 更精确)
    支持 image_path: str 路径 或 PIL.Image 对象
    """
    # 归一化：PIL Image → 临时文件
    if isinstance(image_path, Image.Image):
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        image_path.save(tmp.name)
        image_path = tmp.name
    img = Image.open(image_path)

    yolo_boxes = _yolo(image_path, conf)
    elements = []

    if mode == 'crop':
        # YOLO元素批量OCR（拼接一次推理）
        labels_map = _ocr_crops_batch(img, yolo_boxes)
        for idx, (x1, y1, x2, y2, c) in enumerate(yolo_boxes):
            elements.append({'bbox': [x1,y1,x2,y2], 'type': 'icon', 'label': labels_map.get(idx), 'confidence': c})
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
    #if [x for x in elements if x['label'] is None]: print('[TIPS] crop grid + VLM to identify target no text icon if needed')
    return elements

def visualize_for_debug(image_path, elements, output_path=None):
    """Only use when user wants to DEBUG!"""
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

def _serve_yolo_daemon():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def handle_one_request(self): self.server.last=time.time(); return super().handle_one_request()
        def do_GET(self):
            if self.path == '/ping':
                self.send_response(200); self.end_headers(); self.wfile.write(b'ui_detect_yolo')
            else:
                self.send_response(404); self.end_headers()
        def do_POST(self):
            try:
                d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                body = json.dumps({'boxes': _yolo_local(d['path'], d.get('conf', 0.25))}).encode('utf-8')
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            except Exception as e:
                body = json.dumps({'error': repr(e)}).encode('utf-8')
                self.send_response(500); self.end_headers(); self.wfile.write(body)
    s=HTTPServer(('127.0.0.1', _YOLO_PORT), H); s.timeout=60; s.last=time.time()
    while time.time()-s.last < 3600: s.handle_request()

if __name__ == '__main__' and '--yolo-daemon' in sys.argv:
    _serve_yolo_daemon()
