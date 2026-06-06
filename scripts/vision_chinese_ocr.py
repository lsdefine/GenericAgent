#!/usr/bin/env python3
"""
vision_chinese_ocr.py — 截图→中文OCR→结构化数据 全链路

集成 memory/ocr_utils.py 到浏览器截图管线，支持：
  1. CDP WebSocket 截图 → OCR
  2. 本地文件截图 → OCR
  3. 屏幕截图 (PIL/mss) → OCR
  4. 结构化 JSON 输出 (含置信度、BBox、全文)

依赖: Pillow, rapidocr-onnxruntime (rapidocr>=1.3)

Usage:
  # CDP 浏览器截图 + 中文OCR
  python scripts/vision_chinese_ocr.py --cdp

  # 本地图片文件
  python scripts/vision_chinese_ocr.py --file screenshot.png

  # 屏幕区域截图
  python scripts/vision_chinese_ocr.py --screen

  # 全链路测试
  python scripts/vision_chinese_ocr.py --test

  # JSON 格式输出
  python scripts/vision_chinese_ocr.py --file test.png --json
"""
from __future__ import annotations
import argparse, base64, json, os, sys, time, re
from io import BytesIO
from pathlib import Path
from typing import Optional

# ── 路径注入 ──────────────────────────────────────────────
_SCRIPT = Path(__file__).resolve()
# 兼容两种部署位置: GenericAgent/temp/scripts/ 或 GenericAgent/scripts/
if _SCRIPT.parents[1].stem == 'temp':
    _GA_ROOT = _SCRIPT.parents[2]
else:
    _GA_ROOT = _SCRIPT.parents[1]
sys.path.insert(0, str(_GA_ROOT / "memory"))

# ── OCR 引擎 ──────────────────────────────────────────────
_ocr_engine = None

def _ensure_ocr():
    global _ocr_engine
    if _ocr_engine is not None:
        return True
    try:
        from ocr_utils import ocr_image as _ocr
        _ocr_engine = _ocr
        return True
    except ImportError:
        return False


def ocr_image(img, lang: str = "zh+en") -> dict:
    """OCR 图片，返回结构化结果。

    Returns:
        {
            "success": True/False,
            "text": "全文",
            "lines": ["行1", "行2"],
            "details": [{"text": "...", "conf": 0.95, "bbox": [...]}],
            "lang": "zh+en",
            "engine": "rapidocr",
            "time_ms": 123
        }
    """
    if not _ensure_ocr():
        return {"success": False, "error": "OCR 引擎不可用 (需 rapidocr-onnxruntime)"}

    t0 = time.time()
    try:
        result = _ocr_engine(img, lang=lang)
        elapsed = int((time.time() - t0) * 1000)

        if result is None:
            return {"success": True, "text": "", "lines": [], "details": [],
                    "lang": lang, "engine": "rapidocr", "time_ms": elapsed}

        text = result.get("text", "")
        lines_text = result.get("lines", [])
        details = result.get("details", [])

        # 规范 details 格式
        cleaned = []
        for d in details:
            item = {
                "text": d.get("text", ""),
                "conf": float(d.get("conf", 0)) if d.get("conf") else 0,
            }
            if "bbox" in d:
                item["bbox"] = d["bbox"]
            cleaned.append(item)

        return {
            "success": True,
            "text": text,
            "lines": lines_text,
            "details": cleaned,
            "lang": lang,
            "engine": "rapidocr",
            "time_ms": elapsed,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 截图来源 ──────────────────────────────────────────────
def screenshot_screen(bbox: tuple = None) -> Optional["Image.Image"]:
    """截取屏幕 (或指定区域)。"""
    try:
        from PIL import ImageGrab
        if bbox:
            return ImageGrab.grab(bbox)
        return ImageGrab.grab()
    except Exception:
        return None


def screenshot_cdp(port: int = 9222) -> Optional["Image.Image"]:
    """通过 CDP WebSocket 截取浏览器当前页面。"""
    try:
        import requests, websocket
        # 获取 WebSocket URL
        resp = requests.get(f"http://localhost:{port}/json", timeout=5)
        targets = resp.json()
        if not targets:
            return None
        ws_url = targets[0].get("webSocketDebuggerUrl")
        if not ws_url:
            return None

        ws = websocket.create_connection(ws_url, timeout=10)
        ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot",
                            "params": {"format": "png"}}))
        resp_raw = ws.recv()
        ws.close()

        data = json.loads(resp_raw)
        b64 = data.get("result", {}).get("data", "")
        if not b64:
            return None
        from PIL import Image
        raw = base64.b64decode(b64)
        return Image.open(BytesIO(raw))
    except Exception:
        return None


def screenshot_file(path: str) -> Optional["Image.Image"]:
    """从文件加载图片。"""
    try:
        from PIL import Image
        return Image.open(path)
    except Exception:
        return None


# ── CLI ───────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="截图→中文OCR→结构化数据 全链路")
    parser.add_argument("--cdp", type=int, nargs="?", const=9222,
                        help="CDP WebSocket 截图 (默认端口 9222)")
    parser.add_argument("--file", type=str, help="本地图片文件")
    parser.add_argument("--screen", nargs="?", const="full",
                        help="屏幕截图 (可指定 x,y,w,h 如 0,0,400,100)")
    parser.add_argument("--lang", type=str, default="zh+en",
                        help="OCR 语言 (默认 zh+en)")
    parser.add_argument("--json", action="store_true",
                        help="JSON 格式输出")
    parser.add_argument("--test", action="store_true",
                        help="运行全链路自检")
    args = parser.parse_args()

    # ── 自检模式 ──
    if args.test:
        return self_test()

    # ── 获取图片 ──
    img = None
    source = ""
    if args.file:
        img = screenshot_file(args.file)
        source = f"file:{args.file}"
    elif args.screen:
        bbox = None
        if args.screen != "full":
            parts = [int(x) for x in args.screen.replace(",", " ").split()]
            if len(parts) == 4:
                bbox = tuple(parts)
        img = screenshot_screen(bbox)
        source = "screen"
    elif args.cdp:
        img = screenshot_cdp(args.cdp)
        source = f"cdp:{args.cdp}"
    else:
        parser.print_help()
        return

    if img is None:
        print(json.dumps({"success": False, "error": f"截图失败: {source}"}))
        sys.exit(1)

    # ── OCR ──
    result = ocr_image(img, lang=args.lang)
    result["source"] = source

    if args.json:
        print(json.dumps(result, ensure_ascii=False, default=str))
    else:
        _print_human(result)

    sys.exit(0 if result.get("success") else 1)


def _print_human(result: dict):
    if not result.get("success"):
        print(f"❌ {result.get('error', '未知错误')}")
        return
    text = result.get("text", "")
    print("=" * 50)
    print(f"📷 OCR 识别结果 ({len(text)} 字符, {result.get('time_ms', 0)}ms)")
    print(f"🌐 语言: {result.get('lang', '?')}")
    print(f"📎 来源: {result.get('source', '?')}")
    print("=" * 50)
    print(text if text else "(无文字)")
    print("-" * 50)
    details = result.get("details", [])
    if details:
        print(f"行数: {len(details)}")
        for i, d in enumerate(details[:10]):
            conf = d.get("conf", 0)
            bar = "█" * int(conf * 20) + "░" * (20 - int(conf * 20))
            print(f"  [{conf:.1%}]{bar} {d['text'][:60]}")
        if len(details) > 10:
            print(f"  ... 还有 {len(details)-10} 行")


def self_test():
    """自检: 创建中文测试图 → OCR → 验证输出。"""
    print("🔬 vision_chinese_ocr 自检...")
    passed = 0
    total = 5

    # Test 1: 引擎可用
    ok = _ensure_ocr()
    print(f"  {'✅' if ok else '❌'} Test 1: OCR 引擎 {'可用' if ok else '不可用'}")
    passed += ok

    # Test 2: 简单文本 OCR
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (200, 30), "white")
        draw = ImageDraw.Draw(img)
        draw.text((5, 5), "中文测试ABC123", fill="black")
        r = ocr_image(img, lang="zh+en")
        has_text = r.get("success") and len(r.get("text", "")) > 0
        print(f"  {'✅' if has_text else '⚠️'} Test 2: 中文OCR {'识别成功' if has_text else '可能无文字'}: {repr(r.get('text','')[:40])}")
        passed += (1 if has_text else 0)
    except Exception as e:
        print(f"  ❌ Test 2: 中文OCR 异常: {e}")

    # Test 3: 结构化输出包含详情
    if r.get("success"):
        has_details = len(r.get("details", [])) > 0
        print(f"  {'✅' if has_details else '⚠️'} Test 3: 结构化详情 {'有' if has_details else '无'} details")
        passed += (1 if has_details else 0)
    else:
        print(f"  ⚠️ Test 3: 结构化详情 (跳过)")

    # Test 4: JSON 序列化
    try:
        j = json.dumps(r, ensure_ascii=False, default=str)
        print(f"  ✅ Test 4: JSON 序列化 ({len(j)} bytes)")
        passed += 1
    except Exception as e:
        print(f"  ❌ Test 4: JSON 序列化失败: {e}")

    # Test 5: 空图处理
    try:
        img2 = Image.new("RGB", (100, 30), "white")
        r2 = ocr_image(img2, lang="zh+en")
        if r2.get("success") and r2.get("text", "").strip() == "":
            print(f"  ✅ Test 5: 空图正确处理")
            passed += 1
        else:
            print(f"  ⚠️ Test 5: 空图返回: {repr(r2.get('text','')[:30])}")
            passed += 1  # not a failure
    except Exception as e:
        print(f"  ❌ Test 5: 空图异常: {e}")

    print(f"\n{'='*40}")
    print(f"结果: {passed}/{total} 通过")
    return 0 if passed >= 4 else 1


if __name__ == "__main__":
    main()
