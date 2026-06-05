---
version: 1.1
last_updated: "2026-06-05"
---

# Vision API SOP

## ⚠️ 前置规则（必须遵守）

1. **先枚举窗口**：调用 vision 前必须先用 `pygetwindow` 枚举窗口标题，确认目标窗口存在且已激活到前台。窗口不存在就不要截图。
2. **🚫 禁止全屏截图**：必须先利用ljqCtrl截取窗口区域。能截局部（如标题栏）就不截整窗口，能截窗口就绝不全屏。全屏截图在任何场景下都不允许。
3. **能不用 vision 就不用**：如果窗口标题/本地 OCR（`ocr_utils.py`）能获取所需信息，就不要调用 vision API，省 token 且更可靠。Vision 是最后手段。

## 快速用法

```python
from vision_api import ask_vision
result = ask_vision(image, prompt="描述图片内容", backend="claude", timeout=60, max_pixels=1_440_000)
# image: 文件路径(str/Path) 或 PIL Image
# backend: 'claude'(默认) | 'openai' | 'modelscope'
# 返回 str：成功为模型回复，失败为 'Error: ...'
```

## Browser-Vision 全链路集成

`scripts/browser-vision.py` 提供 CDP 截图 + 本地 OCR (rapidocr) 的浏览器视觉验证全链路。

### 用法

```bash
# 方式1：CDP管道模式（web_execute_js → base64 → pipe）
web_execute_js script='Page.captureScreenshot' | python3 scripts/browser-vision.py --cdp-screenshot --expect "期望文本"

# 方式2：CDP端口直连截图+OCR
python3 scripts/browser-vision.py --cdp-port 9222 --expect "期望文本" [--save output.png]

# 方式3：对已有截图文件OCR
python3 scripts/browser-vision.py --screenshot screenshot.png [--expect "文本"] [--json]

# 方式4：交互模式
python3 scripts/browser-vision.py --interactive
```

### 典型工作流

1. `web_execute_js` 调用 CDP 截取浏览器标签页
2. base64 数据管道传入 `browser-vision.py --cdp-screenshot`
3. OCR 提取文字 → 验证期望文本 → 返回 JSON 或摘要
4. 可选：`--draw-boxes` 输出 OCR 框叠加图用于调试

### 依赖

- `rapidocr-onnxruntime`：本地 OCR（已安装）
- `Pillow`：图片绘制（已安装）
- `websockets`：CDP WebSocket 直连（备选方式）
- `opencv-python`：可选，缺省时自动降级

## 如果没有 `vision_api.py`，初次构建vision能力

1. 复制 `memory/vision_api.template.py` → `memory/vision_api.py`
2. 只改头部"用户配置区"：去 `mykey.py` 里扫描变量名（⚠️ 只看名字，禁止输出 apikey 值），尝试找能用配置名填入 `CLAUDE_CONFIG_KEY` / `OPENAI_CONFIG_KEY`，`DEFAULT_BACKEND` 选后端，并测试
3. 保底：没有可用 config 时去 `https://modelscope.cn/my/myaccesstoken` 申请 token 填入 `MODELSCOPE_API_KEY`
