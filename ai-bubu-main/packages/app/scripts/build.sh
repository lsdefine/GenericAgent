#!/bin/bash
# 构建 AI 步步 生产版本
cd "$(dirname "$0")/.." || exit 1
pnpm tauri build
