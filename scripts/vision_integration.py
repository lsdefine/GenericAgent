#!/usr/bin/env python3
"""
vision_integration.py — Vision Pipeline 生产化集成模块

将 browser-vision.py + OCR 封装为可导入模块，供日常巡检脚本调用。

验收标准:
  ✓ 可被其他脚本 import
  ✓ 支持文件 OCR (ocr_image)
  ✓ 支持 URL 截图 + OCR (ocr_url)
  ✓ 支持 dashboard 检查 (check_dashboard)
  ✓ CLI 接口

用法:
    from scripts.vision_integration import ocr_image, ocr_url, capture_screenshot, check_dashboard
    
    # 对图片文件 OCR
    text = ocr_image("/path/to/screenshot.png")
    
    # URL → 截图 → OCR
    text, screenshot_path = ocr_url("http://localhost:8899")
    
    # 看板检查 (带期望文本匹配)
    result = check_dashboard("http://localhost:8899", expect_text="正常")

CLI:
    python3 -m scripts.vision_integration ocr-file IMAGE_PATH
    python3 -m scripts.vision_integration ocr URL [--expect TEXT]
    python3 -m scripts.vision_integration capture URL [--output PATH]
    
注意:
    浏览器截图依赖 Chromium 环境。如果系统 Chromium 不可用或 headless 模式异常，
    截图功能会返回 None，但文件 OCR 始终可用。
"""
import os
import sys
import json
import base64
import subprocess
import tempfile
import time
import logging
import argparse
from pathlib import Path
from typing import Optional, Tuple

# ── 项目根 ──────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "memory"))
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
log = logging.getLogger("vision_integration")

# ── OCR 引擎 ───────────────────────────────────────────
def ocr_image(image_path: str, lang: str = "eng") -> str:
    """
    对图片文件进行 OCR 文字识别。
    
    使用 tesseract 命令行 (轻量级，避免 OOM)，
    兜底使用 pytesseract。
    
    参数:
        image_path: 图片文件路径
        lang: OCR 语言 (默认 eng, 可选 chi_sim+eng)
    
    返回:
        识别文本字符串，失败返回空字符串
    """
    if not os.path.isfile(image_path):
        log.error(f"图片文件不存在: {image_path}")
        return ""
    
    # 方法1: 直接 subprocess tesseract (最轻量，已验证可用)
    try:
        result = subprocess.run(
            ['tesseract', image_path, 'stdout', '-l', lang],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            if text:
                log.info(f"tesseract OCR 完成: {len(text)} 字符 (来源: {image_path})")
                return text
        else:
            log.warning(f"tesseract 返回错误码 {result.returncode}: {result.stderr[:200]}")
    except FileNotFoundError:
        log.warning("tesseract 未安装")
    except subprocess.TimeoutExpired:
        log.warning("tesseract 超时")
    except Exception as e:
        log.warning(f"tesseract 异常: {e}")
    
    # 方法2: memory.ocr_utils (rapidocr，可能 OOM)
    try:
        from memory.ocr_utils import ocr_image as _ocr_core
        text = _ocr_core(image_path, lang=lang)
        log.info(f"OCR (memory.ocr_utils) 完成: {len(text)} 字符")
        return text
    except Exception as e:
        log.warning(f"memory.ocr_utils OCR 失败: {e}")
    
    return ""


# ── 浏览器截图 ─────────────────────────────────────────
def _find_chrome() -> Optional[str]:
    """查找系统可用的 Chrome/Chromium 二进制路径。"""
    candidates = [
        "google-chrome", "google-chrome-stable", "google-chrome-beta",
        "chromium-browser", "chromium", "chrome",
        "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    ]
    for name in candidates:
        if "/" in name:
            path = name if os.path.isfile(name) else None
        else:
            result = subprocess.run(["which", name], capture_output=True, text=True)
            path = result.stdout.strip() or None
        if path:
            return path
    return None


def capture_screenshot(url: str, output_path: Optional[str] = None, timeout: int = 25) -> Optional[str]:
    """
    访问 URL 并截图保存。
    
    尝试多种截图方式:
      1. BrowserContext (Xvfb + Selenium, 推荐)
      2. CDP WebSocket (browser-vision.py 管道)
      3. chromium --screenshot (直接子进程)
      4. pyppeteer (异步)
    
    参数:
        url: 目标 URL
        output_path: 截图保存路径，默认自动生成
        timeout: 总体超时秒数
    
    返回:
        截图文件路径，失败返回 None
    """
    if not output_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = url.replace("://", "_").replace("/", "_").replace(":", "_")[:40]
        output_path = str(_PROJECT_ROOT / "screenshots" / f"vision_{timestamp}_{safe_name}.png")
    
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    # 方法1: BrowserContext (Xvfb + Selenium)
    result = _screenshot_browser_context(url, output_path, timeout)
    if result:
        log.info(f"📸 截图成功 (BrowserContext): {output_path}")
        return result
    
    # 方法2: chromium --screenshot 子进程
    result = _screenshot_chromium_direct(url, output_path, timeout)
    if result:
        log.info(f"📸 截图成功 (chromium): {output_path}")
        return result
    
    log.warning(f"所有截图方式均失败: {url}")
    return None


def _screenshot_browser_context(url: str, output_path: str, timeout: int) -> Optional[str]:
    """使用 XvfbContext + BrowserContext 截图。"""
    try:
        from memory.tools.vision_browser_pipeline import XvfbContext, BrowserContext
        
        with XvfbContext(display=":99") as xvfb:
            with BrowserContext(headless=True, page_load_timeout=min(timeout, 20)) as browser:
                browser.navigate(url)
                time.sleep(2)  # 等待渲染
                browser.save_screenshot(output_path)
                if os.path.getsize(output_path) > 1000:
                    return output_path
    except ImportError as e:
        log.debug(f"BrowserContext 不可用: {e}")
    except Exception as e:
        log.debug(f"BrowserContext 失败: {e}")
    return None


def _screenshot_chromium_direct(url: str, output_path: str, timeout: int) -> Optional[str]:
    """使用 chromium-browser --screenshot 直接截图 (通过 xvfb-run)。"""
    chrome = _find_chrome()
    if not chrome:
        return None
    
    try:
        # 使用 xvfb-run 提供虚拟显示
        cmd = [
            "xvfb-run", "--auto-servernum",
            chrome,
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--screenshot={output_path}",
            "--window-size=1280,720",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
            return output_path
        
        # 如果失败，尝试 with data URI
        data_uri = f"data:text/html,<meta http-equiv='refresh' content='0;url={url}'>"
        cmd[-1] = data_uri
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
            return output_path
    except subprocess.TimeoutExpired:
        # 超时但可能已生成截图
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
            return output_path
    except Exception as e:
        log.debug(f"chromium 截图失败: {e}")
    
    return None


# ════════════════════════════════════════════════════════════
#  高层 API
# ════════════════════════════════════════════════════════════

def ocr_url(url: str, lang: str = "chi_sim+eng", save_screenshot: bool = True) -> Tuple[str, Optional[str]]:
    """
    访问 URL → 截图 → OCR 识别文本。
    
    返回:
        (识别文本, 截图路径)
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = url.replace("://", "_").replace("/", "_").replace(":", "_")[:50]
    
    if save_screenshot:
        screenshot_path = str(_PROJECT_ROOT / "screenshots" / f"vision_{timestamp}_{safe_name}.png")
    else:
        screenshot_path = tempfile.mktemp(suffix=".png")
    
    result_path = capture_screenshot(url, screenshot_path)
    if not result_path:
        log.warning(f"无法获取截图: {url}")
        return ("", None)
    
    text = ocr_image(result_path, lang=lang)
    return (text, result_path)


def check_dashboard(url: str = "http://localhost:8899",
                    expect_text: Optional[str] = None,
                    lang: str = "chi_sim+eng") -> dict:
    """
    截健康看板图 + OCR 验证。
    
    返回:
        {
            "url": str,
            "screenshot_path": str or None,
            "ocr_text": str,
            "matched": bool (if expect_text provided),
            "error": str or None
        }
    """
    result = {
        "url": url,
        "screenshot_path": None,
        "ocr_text": "",
        "matched": None,
        "error": None,
    }
    
    try:
        text, screenshot_path = ocr_url(url, lang=lang)
        result["ocr_text"] = text
        result["screenshot_path"] = screenshot_path
        
        if expect_text:
            result["matched"] = expect_text.lower() in text.lower() if text else False
            log.info(f"Dashboard 检查: {'✅' if result['matched'] else '❌'} 期望='{expect_text}'")
        
        log.info(f"Dashboard OCR: {len(text)} 字符, 截图: {screenshot_path}")
    except Exception as e:
        result["error"] = str(e)
        log.error(f"Dashboard 检查失败: {e}")
    
    return result


# ════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Vision Pipeline 生产化集成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 -m scripts.vision_integration ocr-file screenshot.png
  python3 -m scripts.vision_integration ocr http://localhost:8899 --expect "正常"
  python3 -m scripts.vision_integration capture http://localhost:8899 -o /tmp/dash.png
        """
    )
    sub = parser.add_subparsers(dest="command", help="子命令")
    
    # capture
    p_cap = sub.add_parser("capture", help="截图 URL")
    p_cap.add_argument("url", help="目标 URL")
    p_cap.add_argument("--output", "-o", help="输出路径")
    
    # ocr (URL → 截图 → OCR)
    p_ocr = sub.add_parser("ocr", help="URL 截图 + OCR")
    p_ocr.add_argument("url", help="目标 URL")
    p_ocr.add_argument("--expect", "-e", help="期望匹配文本")
    p_ocr.add_argument("--lang", default="chi_sim+eng", help="OCR 语言")
    p_ocr.add_argument("--no-save", action="store_true", help="不保留截图")
    
    # ocr-file
    p_of = sub.add_parser("ocr-file", help="对图片文件 OCR")
    p_of.add_argument("image_path", help="图片路径")
    p_of.add_argument("--lang", default="eng", help="OCR 语言 (chi_sim+eng 需更多内存)")
    
    # dashboard
    p_db = sub.add_parser("dashboard", help="健康看板检查")
    p_db.add_argument("--url", default="http://localhost:8899", help="看板 URL")
    p_db.add_argument("--expect", "-e", help="期望匹配文本")
    p_db.add_argument("--lang", default="chi_sim+eng", help="OCR 语言")
    p_db.add_argument("--json", action="store_true", help="JSON 格式输出")
    
    args = parser.parse_args()
    
    if args.command == "capture":
        path = capture_screenshot(args.url, args.output)
        if path:
            print(f"✅ 截图: {path}")
        else:
            print("❌ 截图失败")
            sys.exit(1)
    
    elif args.command == "ocr":
        text, sc_path = ocr_url(args.url, lang=args.lang, save_screenshot=not args.no_save)
        print(f"📝 OCR 文本 ({len(text)} 字符):")
        if text:
            print(text[:1000] + ("..." if len(text) > 1000 else ""))
        if sc_path:
            print(f"📸 截图: {sc_path}")
        if args.expect:
            matched = args.expect.lower() in text.lower()
            print(f"{'✅' if matched else '❌'} 期望文本 '{args.expect}': {'匹配' if matched else '不匹配'}")
    
    elif args.command == "ocr-file":
        text = ocr_image(args.image_path, lang=args.lang)
        print(f"📝 OCR 文本 ({len(text)} 字符):")
        if text:
            print(text[:1000] + ("..." if len(text) > 1000 else ""))
        else:
            print("(无识别结果)")
    
    elif args.command == "dashboard":
        result = check_dashboard(url=args.url, expect_text=args.expect, lang=args.lang)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"URL: {result['url']}")
            print(f"截图: {result['screenshot_path'] or '失败'}")
            print(f"OCR 文本 ({len(result['ocr_text'])} 字符):")
            if result['ocr_text']:
                print(result['ocr_text'][:500])
            if result['matched'] is not None:
                print(f"{'✅' if result['matched'] else '❌'} 匹配: {result['matched']}")
            if result['error']:
                print(f"⚠️ 错误: {result['error']}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
