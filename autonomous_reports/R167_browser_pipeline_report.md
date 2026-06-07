---
version: 1.0
task: v44-4
title: Browserless全链路管道构建
date: 2026-06-06
status: completed
---

# Browserless 全链路管道报告

## 现存资产盘点
- **TMWebDriver**: TMWebDriver.py (14693B), assets/tmwd_cdp_bridge/ 已就绪
- **scripts/browser_interact.py**: BrowserInteract类, 支持 navigate/click/fill/screenshot/ocr
- **scripts/browser-vision.py**: CDP截图 + OCR + 文本断言, 支持CDP WebSocket
- **scripts/browser_click.py**: 点击自动化
- **temp/vision_browser_pipeline.py**: 725行, Xvfb + 浏览器集成
- **Selenium 3.141.0** + **playwright-stealth 1.0.5** 已安装
- **Hermes browser tool**: ✓ enabled

## 管道构建
创建 **temp/browser_pipeline.py** (192行) 统一入口:
- 支持 headless/visible 模式
- URL导航 → 截图 → Vision分析 → OCR一条龙
- JSON/文本输出
- 自动保存截图到 screenshots/

## 验收结果
- ✅ 测试1: https://example.com → 浏览器截图成功 (1280×633, 18KB)
- ✅ 测试2: 截图 → Vision分析 (mock后端, 正确提取页面文字"Example Domain...")
- ✅ 可复用: CLI支持 --url/--screenshot/--vision/--ocr/--json 等参数

## 管道用法
```bash
# URL截图
python3 temp/browser_pipeline.py https://example.com

# 截图+视觉分析
python3 temp/browser_pipeline.py --screenshot shot.png --vision

# JSON输出
python3 temp/browser_pipeline.py https://example.com --json
```

## 待改进
- real Vision API (AUXILIARY_VISION_* env vars) 尚未集成到vision_api.py
- CDP 9222端口未启用 (需启动Chrome时加 --remote-debugging-port=9222)
