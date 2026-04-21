"""
本地 OCR 工具
- OCR引擎: rapidocr-openvino (优先, ~0.25s/次) 或 rapidocr-onnxruntime (备选)
- 坑(rapid): result[i][2] conf 是 str 不是 float
- 坑(rapid): 无文字时 result 返回 None 而非空列表
- 坑: enhance 放大+高对比度处理，对清晰文字有害，默认关闭
- 坑(远程桌面): ImageGrab/mss 在 RDP 断开后截图全黑，用 ocr_window(hwnd) 代替
- 2026-04-17: 切换默认引擎为openvino,绕过onnxruntime DLL冲突
"""
import re
from PIL import ImageGrab, Image, ImageEnhance

_LANG = 'zh-Hans-CN'
_engine = None

def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    # 优先使用 openvino 后端 (避免 onnxruntime DLL 冲突)
    try:
        from rapidocr_openvino import RapidOCR
        _engine = ('openvino', RapidOCR())
        return _engine
    except ImportError:
        pass
    # 备选: onnxruntime
    try:
        from rapidocr_onnxruntime import RapidOCR
        _engine = ('onnxruntime', RapidOCR())
        return _engine
    except ImportError:
        pass
    raise RuntimeError("无可用的OCR引擎: rapidocr-openvino 和 rapidocr-onnxruntime 均不可用")

def _preprocess(img, scale=3, contrast=3.0):
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = img.resize((img.width * scale, img.height * scale))
    return img

def _strip_cjk_spaces(t):
    return re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', t)

def _ocr_rapid(img):
    import numpy as np
    backend_name, engine = _get_engine()
    arr = np.array(img)
    result, elapse = engine(arr)
    if not result:
        return {'text': '', 'lines': [], 'details': []}
    lines = [r[1] for r in result]
    details = [{'bbox': r[0], 'text': r[1], 'conf': float(r[2])} for r in result]
    text = _strip_cjk_spaces('\n'.join(lines))
    return {'text': text, 'lines': [_strip_cjk_spaces(l) for l in lines], 'details': details}

def ocr_image(image_input, lang=_LANG, enhance=False, engine=None):
    """
    对 PIL Image 做 OCR
    :param image_input: PIL Image 对象 或 文件路径(str)
    :param lang: 保留参数，当前未使用
    :param enhance: 预处理
    :param engine: 保留参数，当前仅支持 rapid/None
    :return: dict {'text': 全文, 'lines': [行文本], 'details': [bbox+conf]}
    """
    if isinstance(image_input, str):
        image_input = Image.open(image_input)
    if enhance:
        image_input = _preprocess(image_input)
    if engine not in (None, 'rapid'):
        raise ValueError("Only rapid OCR is supported")
    return _ocr_rapid(image_input)

def ocr_screen(bbox=None, lang=_LANG, enhance=False, engine=None):
    """
    截取屏幕区域并 OCR
    :param bbox: (x1, y1, x2, y2) 像素坐标，None=全屏
    :return: dict {'text': 全文, 'lines': [行文本], 'details': [bbox+conf](仅rapid)}
    """
    img = ImageGrab.grab(bbox=bbox)
    return ocr_image(img, lang, enhance, engine)

def ocr_window(hwnd, lang=_LANG, enhance=False, engine=None):
    """
    截取窗口并 OCR (使用 PrintWindow API，支持远程桌面断开场景)
    :param hwnd: 窗口句柄(int)
    :return: dict {'text': 全文, 'lines': [行文本], 'details': [bbox+conf](仅rapid)}
    """
    import win32gui, win32ui
    from ctypes import windll
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    hwndDC = win32gui.GetWindowDC(hwnd)
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    saveDC = mfcDC.CreateCompatibleDC()
    saveBitMap = win32ui.CreateBitmap()
    saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
    saveDC.SelectObject(saveBitMap)
    windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 3)
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)
    win32gui.DeleteObject(saveBitMap.GetHandle())
    saveDC.DeleteDC()
    mfcDC.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwndDC)
    return ocr_image(img, lang, enhance, engine)

if __name__ == "__main__":
    r = ocr_screen((0, 0, 400, 100))
    print(f"识别结果: {r['text']}")
    for line in r['lines']:
        print(f"  行: {line}")
    if 'details' in r:
        for d in r['details']:
            print(f"  [{d['conf']:.3f}] {d['text']}")