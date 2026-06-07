#!/usr/bin/env python3
"""
health_vision.py — 健康巡检视觉检查集成脚本

集成 vision_pipeline (纯Python) 到日常巡检流程。
对健康看板进行截图 + OCR 验证，无需 shell/Xvfb 依赖。

依赖: scripts/vision_pipeline.py, pyvirtualdisplay, mss, tesseract

用法:
    python3 health_vision.py                         # 截图+OCR全屏（默认）
    python3 health_vision.py --url http://localhost:8899  # 打开看板URL后截图+OCR
    python3 health_vision.py --ocr-only /path/to/screenshot.png  # 仅OCR
"""
import sys, os, json, argparse, webbrowser, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.vision_pipeline import capture_and_ocr, ocr_file, start_display, stop_display


def check_health_dashboard(url="http://localhost:8899", expect_text=None, output=None):
    """
    对健康看板进行视觉检查。

    打开 URL → 等待加载 → 截图 → OCR → 返回结果

    返回 dict:
        url, screenshot_path, ocr_text, matched, error
    """
    print(f"🔍 健康看板视觉检查: {url}")
    result = {"url": url, "screenshot_path": None, "ocr_text": None,
              "matched": None, "error": None}

    # 先检查URL是否可达（快速失败）
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=3)
        print(f"  ✅ URL可达: {url}")
    except Exception as e:
        print(f"  ⚠️  URL不可达 ({e})，尝试全屏截图...")
        # 即使不可达，仍尝试截图（可能显示错误页）

    try:
        # 1. 启动虚拟显示器
        if not start_display(visible=False):
            result["error"] = "Failed to start display"
            print(f"  ❌ 错误: {result['error']}")
            return result

        # 2. 在浏览器中打开URL
        print(f"  🌐 打开浏览器: {url}")
        webbrowser.open(url, new=0)
        time.sleep(3)  # 等待页面加载

        # 3. 截图+OCR
        vr = capture_and_ocr(output_path=output, lang='eng', auto_display=False)
        if vr.error:
            result["error"] = vr.error
            print(f"  ❌ 截图/OCR失败: {vr.error}")
            return result

        result["image_path"] = vr.image_path
        result["ocr_text"] = vr.text

        if vr.image_path:
            print(f"  📸 截图: {vr.image_path}")
        print(f"  📝 OCR 文本 ({len(vr.text)} 字符):")
        for line in vr.text.split("\n")[:12]:
            if line.strip():
                print(f"    {line.strip()}")

        # 4. 文本匹配
        if expect_text and vr.text:
            result["matched"] = expect_text.lower() in vr.text.lower()
            status = "✅ 匹配" if result["matched"] else "❌ 不匹配"
            print(f"  {status}: 期望 '{expect_text}'")

        print(f"  ⏱ 耗时: {vr.duration:.2f}s")

    except Exception as e:
        result["error"] = str(e)
        print(f"  ❌ 异常: {e}")

    return result


def ocr_screenshot(path, lang="eng"):
    """对已有截图进行 OCR (轻量文件检查)"""
    if not os.path.isfile(path):
        print(f"❌ 文件不存在: {path}")
        return None

    print(f"🔍 OCR 检查: {path}")
    text = ocr_file(path, lang=lang)
    if text:
        print(f"  📝 识别文本 ({len(text)} 字符):")
        for line in text.split("\n")[:15]:
            if line.strip():
                print(f"    {line.strip()}")
    else:
        print(f"  ⚠️  未识别到文本")
    return text


def main():
    parser = argparse.ArgumentParser(
        description="健康巡检视觉检查 (纯Python, 无shell依赖)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", help="健康看板 URL (默认: 仅截图+OCR全屏)")
    parser.add_argument("--expect", "-e", help="期望匹配文本")
    parser.add_argument("--ocr-only", help="对已有图片文件 OCR (跳过截图)")
    parser.add_argument("--output", "-o", help="截图保存路径")
    parser.add_argument("--lang", default="eng",
                        help="OCR 语言 (默认 eng, 防OOM)")

    args = parser.parse_args()

    if args.ocr_only:
        ocr_screenshot(args.ocr_only, lang=args.lang)
    elif args.url:
        result = check_health_dashboard(
            url=args.url, expect_text=args.expect, output=args.output)
        if args.expect and not result.get("matched"):
            sys.exit(1)
    else:
        # 无URL: 直接截图+OCR全屏
        print("🔍 全屏健康检查 (无URL, 直接截图+OCR)")
        vr = capture_and_ocr(output_path=args.output, lang=args.lang)
        if vr.error:
            print(f"❌ 失败: {vr.error}")
            sys.exit(1)
        print(f"📝 OCR 文本 ({len(vr.text)} 字符):")
        for line in vr.text.split("\n")[:12]:
            if line.strip():
                print(f"    {line.strip()}")
        print(f"⏱ 耗时: {vr.duration:.2f}s")


if __name__ == "__main__":
    main()
