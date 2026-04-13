#!/bin/bash
# 启动 AI 步步 开发服务器
cd "$(dirname "$0")/.." || exit 1
pnpm tauri dev
