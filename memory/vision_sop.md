# Vision API SOP

## ⚠️ 前置规则（必须遵守）

1. **截图前先枚举窗口**：macOS用 `macljqCtrl.ListWindows()` / `ActivateApp()`，Windows用 `pygetwindow`；确认目标窗口存在且已激活到前台。已有图片文件无需枚举窗口。
2. **🚫 禁止全屏截图**：必须先利用ljqCtrl截取窗口区域。能截局部（如标题栏）就不截整窗口，能截窗口就绝不全屏。全屏截图在任何场景下都不允许。
3. **能不用 vision 就不用**：如果窗口标题/本地 OCR（`ocr_utils.py`）能获取所需信息，就不要调用 vision API，省 token 且更可靠。Vision 是最后手段。

## 快速用法

```python
from vision_api import ask_vision
result = ask_vision(image, prompt="描述图片内容", timeout=60)
# 默认 max_pixels=None，保留原尺寸；仅显式 max_pixels=1_440_000 才限制像素数。
# 仍使用 JPEG quality=80，并非无损编码；安卓适配保持同样默认值。
# image: 文件路径(str/Path) 或 PIL Image
# backend: 'openai'(默认) | 'claude' | 'modelscope' | 'auto'
# 默认配置: native_oai_config_dsv4f_11 (mydsv41f / deepseek-v41-flash)
# 已实测文字图和无文字彩色几何图；旧 native_oai_config_dsv4f 测试返回“没有图片”，勿混用
# 旧xAI配置 native_oai_config0 可手动切回（代理随配置）
# 旧配置 native_oai_config15 返回 HTTP 503；备用 native_oai_config_fr113 曾实测识图成功
# 返回 str：成功为模型回复，失败为 'Error: ...'
```

## 本地 OCR（macOS）

- `ocr_utils.ocr_image(path_or_pil)` 默认使用Apple Vision，本地处理；依赖 `pyobjc-framework-Vision`。
- 已实测中英文、数字、空白图、Path/PIL输入及enhance坐标回缩；返回 `text/lines/details`，details含 `bbox/text/conf`。
- bbox是输入图左上原点的四角像素坐标，不能直接当作屏幕绝对坐标。
- `ocr_screen(bbox)` 必填物理像素区域；`ocr_window(window_id)` 走 `macljqCtrl.GrabWindow`。窗口/区域截图需要宿主录屏授权，文件OCR不需要。
- 非macOS默认仍为rapid，也可显式 `engine='rapid'`。字体测试需真实中文字体，PIL默认小字体会产生误导结果。

## 如果没有 `vision_api.py`，初次构建vision能力

1. 复制 `memory/vision_api.template.py` → `memory/vision_api.py`
2. 只改头部"用户配置区"：去 `mykey.py` 里扫描变量名（⚠️ 只看名字，禁止输出 apikey 值），尝试找能用配置名填入 `CLAUDE_CONFIG_KEY` / `OPENAI_CONFIG_KEY`，`DEFAULT_BACKEND` 选后端，并测试
3. 保底：没有可用 config 时去 `https://modelscope.cn/my/myaccesstoken` 申请 token 填入 `MODELSCOPE_API_KEY`
