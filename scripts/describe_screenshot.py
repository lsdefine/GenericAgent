#!/usr/bin/env python3
"""
describe_screenshot.py — 截图→自然语言描述 管线

将截图、OCR、AI视觉描述整合为一条命令。

用法:
  python describe_screenshot.py                          # 全屏截图并描述
  python describe_screenshot.py --window "浏览器"         # 指定窗口
  python describe_screenshot.py --backend mock            # mock后端(无需API密钥)
  python describe_screenshot.py --backend claude          # Claude Vision
  python describe_screenshot.py --backend openai          # GPT-4o
  python describe_screenshot.py --backend modelscope      # ModelScope
  python describe_screenshot.py --save /tmp/ss.jpg        # 保存截图
  python describe_screenshot.py --input /tmp/screenshot.jpg  # 分析已有截图

API:
  from scripts.describe_screenshot import pipeline
  desc = pipeline(input_path="/tmp/screenshot.jpg")
"""

import argparse
import os
import sys
import subprocess
from pathlib import Path

# 添加 scripts 到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.vision_api import ask_vision


def take_screenshot(window: str = None, save_path: str = None) -> str:
    """调用 vision_agent.py 截图，返回截图路径"""
    if save_path is None:
        save_path = "/tmp/describe_screenshot.jpg"
    
    # 确保目录存在
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    
    cmd = [sys.executable, "scripts/vision_agent.py", "screenshot"]
    if window:
        cmd.extend(["--window", window])
    cmd.extend(["--save", save_path])
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"⚠️  vision_agent截图失败: {result.stderr.strip()}")
        print("  尝试直接截图...")
        return _take_screenshot_fallback(save_path)
    
    return save_path


def _take_screenshot_fallback(save_path: str) -> str:
    """备用截图方案"""
    import subprocess
    try:
        # 尝试 import mss (multi-screen screenshot)
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=save_path)
        print(f"  📸 mss截图: {save_path}")
        return save_path
    except ImportError:
        pass
    
    try:
        # 尝试 Xlib
        import Xlib.display
        display = Xlib.display.Display()
        root = display.screen().root
        geom = root.get_geometry()
        w, h = geom.width, geom.height
        # Xlib doesn't easily capture, fall through
    except ImportError:
        pass
    
    # 尝试 import pyscreenshot
    try:
        import pyscreenshot as ImageGrab
        img = ImageGrab.grab()
        img.save(save_path)
        print(f"  📸 pyscreenshot截图: {save_path}")
        return save_path
    except ImportError:
        pass
    
    print("❌ 所有截图方法失败。请安装 mss: pip install mss")
    return None


def pipeline(input_path: str = None, window: str = None,
             backend: str = "mock", prompt: str = "请详细描述这张图片的内容、布局和关键元素") -> str:
    """
    截图→AI描述 完整管线
    
    Args:
        input_path: 图片路径(若为None则新截图)
        window: 窗口标题(可选)
        backend: vision后端(mock/claude/openai/modelscope)
        prompt: 描述提示词
    
    Returns:
        图片描述文本
    """
    # 第1步: 获取截图
    if input_path:
        img_path = input_path
        print(f"📂 分析已有图片: {img_path}")
    else:
        print("📸 开始截图...")
        img_path = take_screenshot(window=window)
        if not img_path:
            return "❌ 截图失败，无法继续"
        print(f"  ✅ 截图保存: {img_path}")
    
    # 第2步: 检查文件是否存在
    if not os.path.exists(img_path):
        return f"❌ 文件不存在: {img_path}"
    
    file_size = os.path.getsize(img_path)
    print(f"  📦 文件大小: {file_size/1024:.1f}KB")
    
    # 第3步: 调用vision API
    print(f"  🤖 调用 {backend} 视觉模型...")
    description = ask_vision(img_path, prompt, backend=backend)
    
    # 第4步: 返回结果
    print()
    print("=" * 50)
    print("📋 AI视觉描述:")
    print("=" * 50)
    print(description)
    print("=" * 50)
    
    return description


def main():
    parser = argparse.ArgumentParser(
        description="截图→自然语言描述 管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--input", help="已有图片路径(不截图)")
    parser.add_argument("--window", help="窗口标题(仅截图时)")
    parser.add_argument("--save", help="截图保存路径")
    parser.add_argument("--backend", default="mock",
                        choices=["mock", "claude", "openai", "modelscope"],
                        help="视觉模型后端 (默认: mock，无需API密钥)")
    parser.add_argument("--prompt", default="请详细描述这张图片的内容、布局和关键元素",
                        help="描述提示词")
    
    args = parser.parse_args()
    
    result = pipeline(
        input_path=args.input,
        window=args.window,
        backend=args.backend,
        prompt=args.prompt
    )
    
    if args.save and args.input:
        import shutil
        shutil.copy2(args.input, args.save)
        print(f"  💾 已复制到: {args.save}")
    
    return 0 if result and not result.startswith("❌") else 1


if __name__ == "__main__":
    sys.exit(main())
