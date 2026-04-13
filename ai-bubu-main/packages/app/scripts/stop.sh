#!/bin/bash
# 停止 AI 步步 开发服务器
pkill -f "target/debug/aibubu" 2>/dev/null
pkill -f "tauri dev" 2>/dev/null
echo "AI 步步 stopped."
