#!/usr/bin/env python3
"""
纯Python Vision Pipeline — 无shell/Xvfb依赖启动
使用 pyvirtualdisplay + mss + pytesseract 实现截图→OCR全链路纯Python

替代: scripts/vision_integration.py (部分), scripts/vision_agent.py (窗口交互部分)
依赖: pip install pyvirtualdisplay mss pytesseract Pillow
"""

import os, sys, time, json, logging, subprocess
from typing import Optional, Tuple, List
from dataclasses import dataclass, field

# 纯Python截图
from mss import mss

# 纯Python图像处理
from PIL import Image

# pytesseract 延迟导入 (仅在需要时, 避免模块级OOM)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('vision_pipeline')

# ─── Display管理 (纯Python, 替代shell启动Xvfb) ────────────────────────
_display: Optional['pyvirtualdisplay.Display'] = None

def start_display(width: int = 1920, height: int = 1080, visible: bool = False) -> bool:
    """启动虚拟显示器 (纯Python, 无shell调用)"""
    global _display
    if _display is not None and _display.is_alive():
        return True
    try:
        from pyvirtualdisplay import Display
        _display = Display(size=(width, height), visible=visible, backend='xvfb')
        _display.start()
        log.info(f"Display started: {width}x{height} on :{_display.display}")
        return True
    except Exception as e:
        log.error(f"Display start failed: {e}")
        return False

def stop_display():
    """停止虚拟显示器"""
    global _display
    if _display:
        try:
            _display.stop()
        except Exception as e:
            log.warning(f"Display stop: {e}")
        _display = None
        log.info("Display stopped")

def get_display_num() -> Optional[str]:
    """获取当前DISPLAY编号"""
    if _display:
        return f":{_display.display}"
    return os.environ.get('DISPLAY')

# ─── 截图模块 (纯Python, 用mss替代xdotool+import) ─────────────────────
def screenshot(monitor: int = 0) -> Optional[Image.Image]:
    """全屏截图 → PIL Image (纯Python)"""
    try:
        with mss() as sct:
            mon = sct.monitors[monitor]  # 0=all, 1=primary, 2+=secondary
            sct_img = sct.grab(mon)
            img = Image.frombytes('RGB', sct_img.size, sct_img.rgb)
            log.info(f"Screenshot taken: {sct_img.size}")
            return img
    except Exception as e:
        log.error(f"Screenshot failed: {e}")
        return None

def screenshot_region(x: int, y: int, w: int, h: int) -> Optional[Image.Image]:
    """区域截图 (纯Python)"""
    try:
        with mss() as sct:
            region = {'left': x, 'top': y, 'width': w, 'height': h}
            sct_img = sct.grab(region)
            img = Image.frombytes('RGB', sct_img.size, sct_img.rgb)
            log.info(f"Region screenshot: ({x},{y},{w},{h})")
            return img
    except Exception as e:
        log.error(f"Region screenshot failed: {e}")
        return None

def screenshot_to_path(output_path: str, monitor: int = 0) -> Optional[str]:
    """截图保存到文件"""
    img = screenshot(monitor)
    if img:
        img.save(output_path)
        log.info(f"Screenshot saved: {output_path}")
        return output_path
    return None

# ─── OCR模块 (subprocess tesseract优先→pytesseract降级) ──────────────
_OCR_TESSERACT_CMD = 'tesseract'

def _ocr_subprocess(image_path: str, lang: str = 'eng') -> str:
    """使用subprocess tesseract (轻量级, 避免OOM)"""
    try:
        result = subprocess.run(
            [_OCR_TESSERACT_CMD, image_path, 'stdout', '-l', lang],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            log.info(f"OCR (subprocess): {len(text)} chars")
            return text
        else:
            log.warning(f"tesseract error {result.returncode}: {result.stderr[:200]}")
    except FileNotFoundError:
        log.warning("tesseract not found")
    except subprocess.TimeoutExpired:
        log.warning("tesseract timeout")
    except Exception as e:
        log.warning(f"tesseract subprocess error: {e}")
    return ""

def ocr_image(image: Image.Image, lang: str = 'eng', max_dim: int = 800) -> str:
    """OCR识别图片中的文字 (先保存到临时文件, 用subprocess tesseract)
    
    参数:
        image: PIL图片
        lang: OCR语言
        max_dim: 最大尺寸 (超此缩小, 防OOM)
    """
    # 缩小大图防OOM
    w, h = image.size
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        new_size = (int(w * ratio), int(h * ratio))
        image = image.resize(new_size, Image.LANCZOS)
        log.info(f"OCR resize: {w}x{h} → {new_size[0]}x{new_size[1]} (防OOM)")
    
    tmp_path = None
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            image.save(f, format='PNG')
            tmp_path = f.name
        # subprocess tesseract (轻量级)
        text = _ocr_subprocess(tmp_path, lang)
        if text:
            return text
        return ""  # subprocess失败不降级pytesseract (防OOM)
    except Exception as e:
        log.error(f"OCR failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass
    return ""

def ocr_file(image_path: str, lang: str = 'eng') -> str:
    """OCR文件图片"""
    text = _ocr_subprocess(image_path, lang)
    if text:
        return text
    return ""

def ocr_data(image: Image.Image, lang: str = 'eng') -> dict:
    """OCR返回结构化数据 (含置信度) — 需pytesseract"""
    try:
        import pytesseract as _pt
        data = _pt.image_to_data(image, lang=lang, output_type=_pt.Output.DICT)
        result = {
            'text': ' '.join([t for t in data['text'] if t.strip()]),
            'words': [{'text': data['text'][i], 'conf': data['conf'][i],
                       'x': data['left'][i], 'y': data['top'][i],
                       'w': data['width'][i], 'h': data['height'][i]}
                      for i in range(len(data['text'])) if data['text'][i].strip()],
            'mean_conf': sum(float(c) for c in data['conf'] if c != '-1') / max(sum(1 for c in data['conf'] if c != '-1'), 1)
        }
        return result
    except Exception as e:
        log.error(f"OCR data failed: {e}")
        return {'text': '', 'words': [], 'mean_conf': 0.0}

# ─── 管道集成 (截图→OCR) ──────────────────────────────────────────────
@dataclass
class VisionResult:
    text: str = ''
    image_path: Optional[str] = None
    display_num: Optional[str] = None
    duration: float = 0.0
    error: Optional[str] = None

def capture_and_ocr(output_path: Optional[str] = None,
                    lang: str = 'eng',
                    auto_display: bool = True) -> VisionResult:
    """完整管道：启动显示器→截图→OCR→返回结果 (全部纯Python)
    
    截图后释放内存图再OCR, 避免子进程OOM.
    """
    result = VisionResult()
    t0 = time.time()

    try:
        # 1. 自动启动显示器
        if auto_display and not os.environ.get('DISPLAY'):
            if not start_display():
                result.error = "Failed to start display"
                return result

        result.display_num = get_display_num()

        # 2. 截图
        img = screenshot()
        if img is None:
            result.error = "Screenshot failed"
            return result

        # 3. 保存到临时文件, 释放内存
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            img.save(f, format='PNG')
            tmp_path = f.name

        # 保存到指定路径 (可选)
        if output_path:
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
            with open(tmp_path, 'rb') as src:
                with open(output_path, 'wb') as dst:
                    dst.write(src.read())
            result.image_path = output_path

        # 释放内存, 避免OCR时OOM
        del img
        import gc; gc.collect()

        # 4. OCR (从文件读取)
        result.text = ocr_file(tmp_path, lang)

        # 清理临时文件
        import os as _os
        _os.unlink(tmp_path)

    except Exception as e:
        result.error = str(e)
    finally:
        result.duration = time.time() - t0

    return result

# ─── CLI ────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description='纯Python Vision Pipeline (无shell依赖)')
    parser.add_argument('action', nargs='?', default='capture',
                        choices=['capture', 'ocr', 'pipe', 'start', 'stop', 'test'])
    parser.add_argument('--output', '-o', default=None, help='截图保存路径')
    parser.add_argument('--lang', '-l', default='eng+chi_sim', help='OCR语言')
    parser.add_argument('--width', type=int, default=1920, help='虚拟显示器宽度')
    parser.add_argument('--height', type=int, default=1080, help='虚拟显示器高度')
    parser.add_argument('--image', '-i', default=None, help='OCR图片路径')
    args = parser.parse_args()

    if args.action == 'start':
        ok = start_display(args.width, args.height)
        print(f"Display: {'✅ started' if ok else '❌ failed'} on {get_display_num()}")
    elif args.action == 'stop':
        stop_display()
        print("Display stopped")
    elif args.action == 'capture':
        path = screenshot_to_path(args.output or 'screenshot.png')
        print(f"Screenshot: {'✅ ' + path if path else '❌ failed'}")
    elif args.action == 'ocr':
        if args.image:
            text = ocr_file(args.image, args.lang)
            print(f"OCR ({args.lang}):\n{text[:500]}")
        else:
            print("❌ Need --image for ocr action")
    elif args.action == 'pipe':
        result = capture_and_ocr(args.output, args.lang)
        print(f"Pipe: {'✅' if result.text else '❌'} | {result.duration:.1f}s | OCR: {len(result.text)} chars")
        if result.error:
            print(f"Error: {result.error}")
        if result.text:
            print(f"Text preview: {result.text[:200]}")
    elif args.action == 'test':
        print("=== Vision Pipeline 自检测试 (纯Python) ===")
        # Test 1: Display (skip if DISPLAY already set)
        has_display = bool(os.environ.get('DISPLAY'))
        if not has_display:
            ok = start_display(visible=False)
            print(f"1. Display: {'✅ pyvirtualdisplay' if ok else '❌'}")
        else:
            print(f"1. Display: ⏭️ already set ({os.environ['DISPLAY']})")
        # Test 2: Screenshot
        img = screenshot()
        print(f"2. Screenshot: {'✅ ' + str(img.size) if img else '❌'}")
        # Test 3: OCR on a small test image (avoid OOM)
        try:
            from PIL import ImageDraw
            sm = Image.new('RGB', (200, 50), 'white')
            ImageDraw.Draw(sm).text((5, 10), 'Hello Pipeline', fill='black')
            text = ocr_image(sm)
            print(f"3. OCR: {'✅ ' + str(len(text)) + ' chars' if text else '⚠️ empty'}")
        except Exception as e:
            print(f"3. OCR: ⚠️ {e}")
        # Test 4: Full pipe (no auto_display since already set)
        result = capture_and_ocr(auto_display=not has_display)
        print(f"4. Pipe: {'✅' if result.text else '⚠️'} {result.duration:.1f}s {len(result.text)} chars")
        print(f"   Error: {result.error or 'none'}")
        print("=== 测试完成 ===")


if __name__ == '__main__':
    main()
