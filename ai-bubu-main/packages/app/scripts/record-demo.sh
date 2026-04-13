#!/bin/bash
# 录制 AI 步步 演示 GIF
#
# 用法：
#   1. 先启动应用: ./scripts/dev.sh
#   2. 运行本脚本: ./scripts/record-demo.sh
#   3. 按照提示操作
#
# 依赖：
#   brew install ffmpeg gifsicle

cd "$(dirname "$0")/.." || exit 1

OUT_DIR="site/public/demo"
mkdir -p "$OUT_DIR"

echo "========================================="
echo "  AI 步步 演示录制工具"
echo "========================================="
echo ""

# 检查依赖
if ! command -v ffmpeg &>/dev/null; then
  echo "需要安装 ffmpeg: brew install ffmpeg"
  exit 1
fi

if ! command -v gifsicle &>/dev/null; then
  echo "需要安装 gifsicle: brew install gifsicle"
  exit 1
fi

echo "准备录制，请确保 AI 步步 已在桌面运行。"
echo ""
echo "录制方式："
echo "  1) 录制桌宠 GIF（推荐 5-10 秒）"
echo "  2) 录制排行榜窗口 GIF"
echo "  3) 截图桌宠"
echo "  4) 截图排行榜窗口"
echo ""
read -rp "选择 (1-4): " choice

case $choice in
  1)
    echo ""
    echo "即将开始录制桌宠..."
    echo "提示：用 Cmd+Shift+5 选择区域录制，"
    echo "      或者用下面的 ffmpeg 命令录制指定区域。"
    echo ""
    read -rp "录屏文件路径 (直接拖入 .mov/.mp4 文件): " VIDEO
    if [ ! -f "$VIDEO" ]; then
      echo "文件不存在: $VIDEO"
      exit 1
    fi
    echo "正在转换为 GIF..."
    ffmpeg -y -i "$VIDEO" -vf "fps=12,scale=400:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 "$OUT_DIR/pet-demo.gif" 2>/dev/null
    gifsicle -O3 --lossy=80 "$OUT_DIR/pet-demo.gif" -o "$OUT_DIR/pet-demo.gif" 2>/dev/null
    echo "✓ 已生成: $OUT_DIR/pet-demo.gif"
    ls -lh "$OUT_DIR/pet-demo.gif"
    ;;
  2)
    echo ""
    read -rp "录屏文件路径 (直接拖入 .mov/.mp4 文件): " VIDEO
    if [ ! -f "$VIDEO" ]; then
      echo "文件不存在: $VIDEO"
      exit 1
    fi
    echo "正在转换为 GIF..."
    ffmpeg -y -i "$VIDEO" -vf "fps=10,scale=520:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 "$OUT_DIR/panel-demo.gif" 2>/dev/null
    gifsicle -O3 --lossy=80 "$OUT_DIR/panel-demo.gif" -o "$OUT_DIR/panel-demo.gif" 2>/dev/null
    echo "✓ 已生成: $OUT_DIR/panel-demo.gif"
    ls -lh "$OUT_DIR/panel-demo.gif"
    ;;
  3)
    echo ""
    echo "3 秒后截图..."
    sleep 3
    screencapture -i "$OUT_DIR/pet-screenshot.png"
    echo "✓ 已生成: $OUT_DIR/pet-screenshot.png"
    ;;
  4)
    echo ""
    echo "3 秒后截图..."
    sleep 3
    screencapture -i "$OUT_DIR/panel-screenshot.png"
    echo "✓ 已生成: $OUT_DIR/panel-screenshot.png"
    ;;
  *)
    echo "无效选择"
    exit 1
    ;;
esac

echo ""
echo "素材已保存到 $OUT_DIR/"
echo "官网会自动使用这些文件。"
