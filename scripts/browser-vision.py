#!/usr/bin/env python3
"""
browser-vision.py — CDP 截图 + 本地 OCR (rapidocr) 的浏览器视觉验证全链路
===========================================================================
集成 TMWebDriver 的 CDP 截图能力 + memory/ocr_utils.py 的本地 OCR 引擎，
支持命令行管道 / WebSocket 直连 / 图片文件 / 交互模式。

依赖: Pillow, rapidocr-onnxruntime, websocket-client (可选)
使用方式: python3 scripts/browser-vision.py --help

版本: 1.0
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Optional

# ── 路径注入 ──────────────────────────────────────────────
_GA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_GA_ROOT / "memory"))

# ── 导入 OCR ──────────────────────────────────────────────
try:
    from ocr_utils import ocr_image, _preprocess
except ImportError:
    # 降级实现
    PIL_AVAILABLE = False
    ocr_image = None
    _preprocess = None
else:
    PIL_AVAILABLE = True

# ── 导入 Vision 预处理 ──────────────────────────────
try:
    from memory.tools.vision_preprocessor import preprocess_pipeline
    VISION_PREPROC_AVAILABLE = True
except ImportError:
    VISION_PREPROC_AVAILABLE = False
    preprocess_pipeline = None


# ═══════════════════════════════════════════════════════════════
#  Helper: Base64 图片 → PIL Image
# ═══════════════════════════════════════════════════════════════
def _b64_to_pil(b64: str) -> "Image.Image":
    from PIL import Image
    raw = base64.b64decode(b64)
    return Image.open(BytesIO(raw))


def _pil_to_b64(img: "Image.Image", fmt: str = "PNG") -> str:
    buf = BytesIO()
    img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


# ═══════════════════════════════════════════════════════════════
#  OCR 核心
# ═══════════════════════════════════════════════════════════════
def _run_ocr(img_path_or_pil) -> dict:
    """OCR 图片，返回结构化结果。"""
    if ocr_image is None:
        return {"text": "", "lines": [], "details": [], "error": "OCR 引擎不可用"}

    from PIL import Image
    if isinstance(img_path_or_pil, str):
        img = Image.open(img_path_or_pil)
    else:
        img = img_path_or_pil

    result = ocr_image(img)
    return result


def ocr_with_expect(img, expect: str, *, json_output: bool = False,
                    draw_boxes: bool = False, save: Optional[str] = None) -> bool:
    """OCR → 文本匹配。返回是否匹配期望文本。"""
    result = ocr_image(img)
    text = result.get("text", "")

    # ── 保存 ──
    if save:
        from PIL import Image
        if isinstance(img, str):
            Image.open(img).save(save)
        else:
            img.save(save)

    # ── JSON 输出 ──
    if json_output:
        result["match"] = False
        result["expected"] = expect if expect else None
        if expect:
            result["match"] = _match_text(text, expect)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return result["match"]

    # ── 人可读输出 ──
    print("=" * 50)
    print(f"📷 OCR 识别结果 ({len(text)} chars)")
    print("=" * 50)
    print(text[:5000] if text else "(无文字)")
    print("-" * 50)

    if expect:
        matched = _match_text(text, expect)
        status = "✅ 匹配" if matched else "❌ 不匹配"
        print(f"期望文本: {expect}")
        print(f"判定: {status}")
        return matched

    return True


def _match_text(text: str, expect: str) -> bool:
    """宽松匹配：去空白+大小写不敏感子串匹配"""
    t = re.sub(r'\s+', '', text.lower())
    e = re.sub(r'\s+', '', expect.lower())
    return e in t or t in e


# ═══════════════════════════════════════════════════════════════
#  CDP 管道模式（从 stdin 读取 base64 截图数据）
# ═══════════════════════════════════════════════════════════════
def cdp_screenshot_pipe(expect: str = "", json_output: bool = False,
                        save: Optional[str] = None,
                        preprocess: str = "none") -> bool:
    """从 stdin 读取 CDP Page.captureScreenshot 返回的 base64 数据。"""
    raw = sys.stdin.read().strip()
    if not raw:
        print("❌ stdin 无数据", file=sys.stderr)
        return False
    try:
        # 可能输入是整个 CDP 结果 JSON
        data = json.loads(raw)
        b64 = data.get("data", data.get("result", {}).get("data", raw))
    except (json.JSONDecodeError, AttributeError, KeyError):
        b64 = raw

    img = _b64_to_pil(b64)
    # ── 预处理 ──
    if preprocess and preprocess != "none" and VISION_PREPROC_AVAILABLE:
        try:
            img = preprocess_pipeline(img, pipeline=preprocess)
        except Exception as e:
            print(f"⚠️  预处理失败 ({preprocess}): {e}", file=sys.stderr)
    if save:
        img.save(save)
    return ocr_with_expect(img, expect, json_output=json_output, save=save)


# ═══════════════════════════════════════════════════════════════
#  Chrome 自动启动助手
# ═══════════════════════════════════════════════════════════════
_CHROME_PROC: Optional[subprocess.Popen] = None

def _find_chrome() -> Optional[str]:
    """查找系统可用的 Chrome/Chromium 二进制路径。"""
    candidates = [
        "google-chrome", "google-chrome-stable", "google-chrome-beta",
        "chromium-browser", "chromium", "chrome",
        "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
        "/snap/bin/chromium",
    ]
    for name in candidates:
        path = shutil.which(name) if "/" not in name else (name if os.path.isfile(name) else None)
        if path:
            return path
    return None

def _launch_chrome(cdp_port: int = 9222, url: str = "about:blank") -> Optional[subprocess.Popen]:
    """启动无头 Chromium 并开启 CDP 远程调试端口。"""
    global _CHROME_PROC
    chrome = _find_chrome()
    if not chrome:
        print("⚠️  未找到 Chrome/Chromium 二进制，跳过自动启动", file=sys.stderr)
        return None

    print(f"🚀 启动无头 Chromium (CDP port {cdp_port})...", file=sys.stderr)
    try:
        proc = subprocess.Popen(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             f"--remote-debugging-port={cdp_port}",
             "--remote-allow-origins=*",
             url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # 等待端口就绪
        for i in range(10):
            time.sleep(0.5)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect(("127.0.0.1", cdp_port))
                s.close()
                _CHROME_PROC = proc
                print(f"✅ Chromium 已就绪 (PID {proc.pid})", file=sys.stderr)
                return proc
            except ConnectionRefusedError:
                s.close()
                continue
        # 超时
        print("⚠️  Chromium 启动超时", file=sys.stderr)
        proc.terminate()
        return None
    except Exception as e:
        print(f"❌ 启动 Chromium 失败: {e}", file=sys.stderr)
        return None

def _cleanup_chrome():
    """清理自动启动的 Chrome 进程。"""
    global _CHROME_PROC
    if _CHROME_PROC and _CHROME_PROC.poll() is None:
        try:
            os.killpg(os.getpgid(_CHROME_PROC.pid), signal.SIGTERM)
            _CHROME_PROC.wait(timeout=3)
        except (ProcessLookupError, OSError):
            pass
        except subprocess.TimeoutExpired:
            _CHROME_PROC.kill()
        _CHROME_PROC = None


# ═══════════════════════════════════════════════════════════════
#  CDP WebSocket 模式（直连浏览器 DevTools）
# ═══════════════════════════════════════════════════════════════
def cdp_websocket(cdp_port: int = 9222, expect: str = "",
                  json_output: bool = False, save: Optional[str] = None,
                  auto_close: bool = True, auto_launch: bool = True,
                  preprocess: str = "none") -> bool:
    """通过 WebSocket 连接 CDP，截取当前页面截图。

    auto_launch: CDP 端口不可用时自动启动无头 Chromium。
    """
    try:
        import websocket
        import requests
    except ImportError:
        print("❌ 需要 websocket-client + requests: pip install websocket-client requests",
              file=sys.stderr)
        return False

    # ── 自动启动 Chrome ──
    if auto_launch:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", cdp_port))
            s.close()
        except ConnectionRefusedError:
            s.close()
            _launch_chrome(cdp_port=cdp_port)
            # 注册退出清理
            import atexit
            atexit.register(_cleanup_chrome)

    # 获取 WebSocket URL
    try:
        resp = requests.get(f"http://localhost:{cdp_port}/json", timeout=5)
        targets = resp.json()
        if not targets:
            print("❌ 无浏览器标签页", file=sys.stderr)
            return False
        # 优先选 non-DevTools 页面
        for t in targets:
            url = t.get("url", "")
            if "devtools://" not in url and "chrome-extension://" not in url:
                ws_url = t.get("webSocketDebuggerUrl")
                break
        else:
            ws_url = targets[0].get("webSocketDebuggerUrl")
        if not ws_url:
            print("❌ 无法获取 WebSocket URL", file=sys.stderr)
            return False
    except Exception as e:
        print(f"❌ 连接 CDP 失败: {e}", file=sys.stderr)
        return False

    # 发送 Page.captureScreenshot 命令
    ws = websocket.create_connection(ws_url, timeout=10)
    req_id = 1
    ws.send(json.dumps({"id": req_id, "method": "Page.captureScreenshot",
                        "params": {"format": "png"}}))
    resp_raw = ws.recv()
    if auto_close:
        ws.close()

    try:
        resp = json.loads(resp_raw)
        b64 = resp.get("result", {}).get("data", "")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"❌ 解析 CDP 响应失败: {e}", file=sys.stderr)
        return False

    if not b64:
        print("❌ CDP 返回空截图数据", file=sys.stderr)
        return False

    img = _b64_to_pil(b64)
    # ── 预处理 ──
    if preprocess and preprocess != "none" and VISION_PREPROC_AVAILABLE:
        try:
            img = preprocess_pipeline(img, pipeline=preprocess)
        except Exception as e:
            print(f"⚠️  预处理失败 ({preprocess}): {e}", file=sys.stderr)
    if save:
        img.save(save)
    return ocr_with_expect(img, expect, json_output=json_output, save=save)


# ═══════════════════════════════════════════════════════════════
#  TMWebDriver 集成 (CDP 截图 via web_execute_js)
# ═══════════════════════════════════════════════════════════════
def tmwebdriver_screenshot(expect: str = "", json_output: bool = False,
                           save: Optional[str] = None) -> bool:
    """通过 TMWebDriver 的 web_execute_js 获取 CDP 截图。"""
    # 尝试导入 tmwebdriver
    return cdp_websocket(cdp_port=9222, expect=expect,
                         json_output=json_output, save=save)


# ═══════════════════════════════════════════════════════════════
#  交互模式
# ═══════════════════════════════════════════════════════════════
def interactive_mode():
    """交互式 OCR 验证。"""
    print("🧪 browser-vision.py 交互模式")
    print("支持命令: screenshot [文件路径] | expect <文本> | cdp | help | quit")
    expect_text = ""
    while True:
        cmd = input(">> ").strip()
        if cmd in ("q", "quit", "exit"):
            break
        elif cmd == "help":
            print("screenshot <path>  - OCR 指定图片")
            print("expect <text>     - 设置期望文本")
            print("cdp               - 从 CDP 截图(port 9222)")
            print("help              - 帮助")
            print("quit              - 退出")
        elif cmd.startswith("expect "):
            expect_text = cmd[7:]
            print(f"期望文本已设为: {expect_text}")
        elif cmd.startswith("screenshot "):
            path = cmd[11:]
            if not os.path.isfile(path):
                print(f"❌ 文件不存在: {path}")
            else:
                ocr_with_expect(path, expect_text)
        elif cmd == "cdp":
            cdp_websocket(cdp_port=9222, expect=expect_text, auto_launch=True)
        else:
            print(f"未知命令: {cmd}")


# ═══════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="浏览器视觉验证工具 — CDP 截图 + OCR + 文本断言")
    parser.add_argument("--cdp-screenshot", action="store_true",
                        help="从 stdin 读取 CDP 截图的 base64 数据")
    parser.add_argument("--cdp-port", type=int, default=0,
                        help="CDP WebSocket 端口 (默认 9222)")
    parser.add_argument("--auto-launch", action="store_true", default=True,
                        help="CDP 端口不可用时自动启动无头 Chromium (默认开启)")
    parser.add_argument("--no-launch", dest="auto_launch", action="store_false",
                        help="禁止自动启动 Chromium")
    parser.add_argument("--launch-url", type=str, default="about:blank",
                        help="自动启动时打开的 URL (默认 about:blank)")
    parser.add_argument("--screenshot", type=str,
                        help="本地截图文件路径")
    parser.add_argument("--expect", type=str, default="",
                        help="期望匹配文本")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="JSON 格式输出")
    parser.add_argument("--save", type=str, default=None,
                        help="保存截图到文件")
    parser.add_argument("--interactive", action="store_true",
                        help="交互模式")
    parser.add_argument("--preprocess", type=str, default="none",
                        choices=["none", "minimal", "best", "binary", "sharp", "ocr_utils"],
                        help="预处理管线: none|minimal|best|binary|sharp|ocr_utils (默认 none)")

    args = parser.parse_args()

    # ── 交互模式 ──
    if args.interactive:
        return interactive_mode()

    # ── CDP 管道模式 ──
    if args.cdp_screenshot:
        return cdp_screenshot_pipe(
            expect=args.expect,
            json_output=args.json_output,
            save=args.save,
            preprocess=args.preprocess)

    # ── CDP WebSocket 模式 ──
    if args.cdp_port:
        # 若用户指定 --no-launch 且端口不可达，立即报错而非自动启动
        if not args.auto_launch:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect(("127.0.0.1", args.cdp_port))
                s.close()
            except ConnectionRefusedError:
                s.close()
                print(f"❌ CDP port {args.cdp_port} 不可达 (使用 --auto-launch 自动启动)", file=sys.stderr)
                return False
        return cdp_websocket(
            cdp_port=args.cdp_port,
            expect=args.expect,
            json_output=args.json_output,
            save=args.save,
            auto_close=True,
            auto_launch=args.auto_launch,
            preprocess=args.preprocess)

    # ── 本地截图文件 ──
    if args.screenshot:
        return ocr_with_expect(
            args.screenshot,
            args.expect,
            json_output=args.json_output,
            save=args.save)

    # ── 默认：无参数 → 尝试 CDP WebSocket (带自动启动) ──
    print("⚠️  未指定模式，尝试 CDP WebSocket (port 9222)...")
    if cdp_websocket(cdp_port=9222, expect=args.expect,
                     json_output=args.json_output, save=args.save,
                     auto_close=True, auto_launch=args.auto_launch,
                     preprocess=args.preprocess):
        return
    print("❌ CDP 不可用，尝试本地截图...")
    for p in ["screenshot.png", "/tmp/screenshot.png"]:
        if os.path.isfile(p):
            ocr_with_expect(p, args.expect,
                            json_output=args.json_output,
                            save=args.save)
            return
    # 回退：用 ljqCtrl 截图
    print("📸 尝试 ljqCtrl 截图...")
    _fallback_screenshot(args.expect, args.json_output, args.save)


def _fallback_screenshot(expect: str = "", json_output: bool = False,
                         save: Optional[str] = None):
    """回退方案：通过 ljqCtrl 截图后 OCR。"""
    try:
        sys.path.insert(0, str(_GA_ROOT / "memory"))
        from ljqCtrl_sop import ljqCtrl
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        ljqCtrl.screenshot(tmp)
        ocr_with_expect(tmp, expect, json_output=json_output, save=save or tmp)
    except ImportError:
        print("❌ ljqCtrl 不可用，无法截图", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
