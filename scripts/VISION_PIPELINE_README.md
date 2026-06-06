# Vision Pipeline 生产化集成

## 概述

Vision Pipeline 将 browser-vision.py + OCR 封装为可导入模块，供日常巡检脚本调用。

## 文件结构

```
scripts/
├── vision_integration.py      # 核心集成模块 (可 import)
├── health_vision.py            # 健康巡检视觉检查脚本
├── browser-vision.py           # 浏览器截图工具 (底层)
└── VISION_PIPELINE_README.md   # 本文件
memory/
├── ocr_utils.py                # OCR 工具 (rapidocr)
└── tools/vision_browser_pipeline.py  # 浏览器管道 (Xvfb+Selenium)
```

## 使用方式

### 1. 作为 Python 模块导入

```python
from scripts.vision_integration import ocr_image, capture_screenshot, check_dashboard

# 文件 OCR
text = ocr_image("/path/to/screenshot.png")          # 英文 (默认)
text = ocr_image("/path/to/screenshot.png", lang="chi_sim+eng")  # 中文

# URL 截图 + OCR (浏览器可用时)
text, screenshot_path = ocr_url("http://localhost:8899")

# 健康看板检查
result = check_dashboard("http://localhost:8899", expect_text="正常运行")
```

### 2. CLI 命令行

```bash
# 对图片文件 OCR
python3 -m scripts.vision_integration ocr-file screenshot.png

# URL 截图 + OCR
python3 -m scripts.vision_integration ocr http://localhost:8899 --expect "正常"

# 仅截图
python3 -m scripts.vision_integration capture http://localhost:8899 -o /tmp/dash.png
```

### 3. 健康巡检视觉检查

```bash
# 直接检查看板
python3 scripts/health_vision.py --url http://localhost:8899

# 对已有截图 OCR
python3 scripts/health_vision.py --ocr-only /tmp/screenshot.png

# 带期望文本验证
python3 scripts/health_vision.py --url http://localhost:8899 --expect "正常运行"
```

## OCR 引擎

| 引擎 | 内存消耗 | 中文支持 | 状态 |
|------|----------|----------|------|
| tesseract (subprocess) | 低 (~50MB) | chi_sim | ✅ 默认 |
| memory.ocr_utils (rapidocr) | 高 (~500MB) | 原生中文 | ⚠️ OOM 风险 |
| pytesseract | 中 | 需 chi_sim | ⚠️ OOM 风险 |

**默认使用 tesseract 命令行** (最轻量，已验证可用)。

## ⚠️ 已知限制

1. **浏览器截图不可用**: 系统 Chromium headless 模式异常
   - CDP WebSocket 超时
   - Selenium 卡死
   - Pyppeteer 无法创建页面
   - `chromium-browser --screenshot` 挂起
   - **根因**: 系统内存不足 (仅 ~650MB 可用) + Chromium sandbox 兼容性问题
   
2. **中文 OCR 需注意内存**: `chi_sim+eng` 语言包需要更多内存
   - 系统可用内存 < 700MB 时建议仅使用 `eng`
   - 中文 OCR 建议在内存充足时使用 `--lang chi_sim+eng`

3. **文件 OCR 始终可用**: 对已有截图的 OCR 功能稳定可用

## 巡检集成

`health_vision.py` 已集成到 `health_unified.sh` 调用链路:

```bash
# 一键执行
python3 scripts/health_vision.py --url http://localhost:8899
```

如需在 `health_dashboard.py` 中集成，可添加:

```python
from scripts.vision_integration import ocr_image
# 在报告生成后 OCR 验证
text = ocr_image("/tmp/dashboard_screenshot.png")
```
