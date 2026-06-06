---
version: 1.3
last_updated: "2026-06-07"
---

# Vision SOP

## ⚠️ 前置规则（必须遵守）

1. **先枚举窗口**：调用 vision 前必须先用 `pygetwindow` 枚举窗口标题，确认目标窗口存在且已激活到前台。窗口不存在就不要截图。
2. **🚫 禁止全屏截图**：必须先利用ljqCtrl截取窗口区域。能截局部（如标题栏）就不截整窗口，能截窗口就绝不全屏。全屏截图在任何场景下都不允许。
3. **能不用 vision 就不用**：如果窗口标题/本地 OCR（`ocr_utils.py`）能获取所需信息，就不要调用 vision API，省 token 且更可靠。Vision 是最后手段。

---

## 1. 核心 OCR API (`memory/tools/vision_browser_pipeline.py`)

主程 OCR 管线：截图 → 预处理 → OCR提取 → 断言。

### 1.1 `ocr_image` — OCR 文本提取

```python
from vision_browser_pipeline import ocr_image, assert_visible, ocr_data

text = ocr_image(image, lang='eng', preprocess='light', engine='auto')
```

**参数:**

| 参数 | 类型 | 默认值 | 说明 |
|:-----|:-----|:-------|:-----|
| `image` | PIL Image / str / Path | 必填 | 图片对象或文件路径 |
| `lang` | str | `'eng'` | OCR 语言（中文用 `'chi_sim+eng'`） |
| `preprocess` | str / bool | `'light'` ⭐ | 预处理管线名称（见下方） |
| `engine` | str | `'auto'` | OCR 引擎: `'auto'` / `'tesseract'` / `'rapidocr'` |

**preprocess 选项（5种管线）:**

| 模式 | 说明 | 适用场景 |
|:-----|:-----|:---------|
| `'light'` ⭐ | 轻度对比度增强 + 极轻微锐化（保持颜色） | **默认**，正常文本 |
| `'best'` | 放大2x + 灰度 + 对比度增强 | 小字/低清晰度 |
| `'binary'` | 放大2x + 自适应二值化 | 文字与背景对比强 |
| `'sharp'` | 灰度 + 锐化 + 对比度增强 | 模糊文本 |
| `'minimal'` | 仅灰度 | 极简场景 |
| `False` / `''` | 不预处理 | 原始图片 |

**返回:** 提取的文本字符串（空字符串表示未识别到文字）。

**引擎选择与 fallback:**
- `engine='auto'`: Tesseract 优先; 含中文时若 Tesseract 结果为空则 fallback 到 RapidOCR
- 显式指定 `'tesseract'` 或 `'rapidocr'` 则锁定引擎
- RapidOCR 性能较差（~11.7s），仅作 fallback

### 1.2 `assert_visible` / `assert_not_visible` — 文本断言

```python
assert_visible(ocr_text, expected, case_sensitive=False, msg=None)
assert_not_visible(ocr_text, expected, case_sensitive=False, msg=None)
```

- **通过**: 返回 `True`
- **失败**: 抛出 `AssertionError`

### 1.3 `ocr_data` — 带边界框的 OCR 数据

```python
results = ocr_data(image, lang='eng')
# 返回: [{"text": str, "conf": float, "bbox": (x1,y1,x2,y2)}, ...]
```

---

## 2. 预处理管线集成 (`memory/tools/vision_preprocessor.py`)

`vision_preprocessor` 已集成到 `vision_browser_pipeline` 中：

```python
# 自动导入（vision_browser_pipeline.py 第 36-41 行）
try:
    from memory.tools.vision_preprocessor import preprocess_pipeline
    _HAS_VISION_PP = True
except ImportError:
    _HAS_VISION_PP = False
```

`ocr_image()` 调用时自动触发预处理：

- `preprocess` 为字符串时 → 调用 `vision_preprocessor.preprocess_pipeline(image, pipeline)`
- `preprocess` 为 `True` → 等效 `'light'`
- 若 `vision_preprocessor` 不可用 → 回退到内置的放大+对比度 fallback

**独立使用:**

```bash
python3 memory/tools/vision_preprocessor.py <image_path> [--pipeline best|light|binary]
```

---

## 3. Browser 全链路集成

### 3.1 `BrowserContext` — 浏览器自动化

```python
from vision_browser_pipeline import BrowserContext

with BrowserContext() as browser:
    browser.navigate("https://example.com")
    img = browser.screenshot()                       # PIL Image
    browser.save_screenshot("page.png")               # 保存到文件
    text = browser.get_text()                         # 页面可见文本
```

**默认配置:** headless, eager 加载策略, 30s 超时, JPEG 压缩截图（quality=85）。

### 3.2 `XvfbContext` — 虚拟显示

```python
from vision_browser_pipeline import XvfbContext

with XvfbContext() as xvfb:       # 自动启动/关闭 Xvfb
    with BrowserContext() as browser:
        ...
```

### 3.3 全链路示例

```python
from vision_browser_pipeline import XvfbContext, BrowserContext, ocr_image, assert_visible

with XvfbContext():
    with BrowserContext() as browser:
        browser.navigate("https://example.com")
        img = browser.screenshot()
        text = ocr_image(img, lang='eng', preprocess='light')
        assert_visible(text, "Example", msg="期望页面包含 Example")
```

---

## 4. 导航优化（eager 策略 + 超时降级）

基于 R227 实测，`page_load_strategy='eager'` 将远程页面导航从 **>30s → ~8s（-73%）**，已在 `BrowserContext` 中默认启用。

| 策略 | `page_load_strategy` | 导航耗时 (httpbin.org) | 说明 |
|:----|:--------------------|:---------------------|:----|
| normal（默认） | `'normal'` | >30s TIMEOUT | 等待所有子资源 |
| **eager ⭐** | `'eager'` | **~8s ✅** | DOMContentLoaded 即返回 |
| none | `'none'` | 30.30s | 立即返回，需手动等待 |

```python
# 默认已启用 eager
ctx = BrowserContext()  # page_load_strategy='eager'

# 如需恢复旧行为
ctx = BrowserContext(page_load_strategy='normal')

# 超时降级: 30s 超时 → 截图当前已渲染内容
ctx = BrowserContext(page_load_timeout=30)
```

**注意:** eager 对动态 JS 渲染可能截到未完全加载的 DOM，建议搭配 `WebDriverWait`。

---

## 5. Cloud Vision API (`vision_api.py`)

用于复杂图片理解（非纯文本提取）, 支持 Claude / OpenAI / ModelScope。

```python
from vision_api import ask_vision
result = ask_vision(image, prompt="描述图片内容", backend="claude", timeout=60, max_pixels=1_440_000)
```

**设置:**
1. 复制 `memory/vision_api.template.py` → `memory/vision_api.py`
2. 在 `mykey.py` 中扫描可用 API Key 变量名
3. 填入 `CLAUDE_CONFIG_KEY` / `OPENAI_CONFIG_KEY`，设置 `DEFAULT_BACKEND`
4. 无可用配置时去 `https://modelscope.cn/my/myaccesstoken` 申请 token

---

## 6. 旧版工具 (`scripts/browser-vision.py`)

`scripts/browser-vision.py` 是早期 CLI 工具，功能已被 `memory/tools/vision_browser_pipeline.py` 取代。

旧版用法（仅作参考）:
```bash
# CDP 管道模式（已弃用，建议使用 vision_browser_pipeline）
web_execute_js script='Page.captureScreenshot' | python3 scripts/browser-vision.py --cdp-screenshot --expect "期望文本"
```
