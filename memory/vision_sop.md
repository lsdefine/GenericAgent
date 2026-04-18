# Vision API SOP

## ⚠️ 前置规则（必须遵守）

1. **先枚举窗口**：调用 vision 前必须先用 `pygetwindow` 枚举窗口标题，确认目标窗口存在且已激活到前台。窗口不存在就不要截图。
2. **🚫 禁止全屏截图**：必须先 `win32gui.GetWindowRect` 获取目标窗口坐标，再 `ImageGrab.grab(bbox=...)` 截窗口区域。能截局部（如标题栏）就不截整窗口，能截窗口就绝不全屏。全屏截图在任何场景下都不允许。
3. **能不用 vision 就不用**：如果窗口标题/本地 OCR（`ocr_utils.py`）能获取所需信息，就不要调用 vision API，省 token 且更可靠。Vision 是最后手段。

## 快速用法

### 函数签名
```python
ask_vision(
    image_input,
    prompt: str | None = None,
    timeout: int = 60,
    max_pixels: int = 1_440_000,
) -> str
```

### 示例
```python
from vision_api import ask_vision
result = ask_vision("image.png", prompt="描述图片内容")  # 路径或PIL Image均可
```
返回 `str`：成功为模型回复，失败为 `Error: ...`。

### 本仓库本地通用封装（代码根 `vision_core.py`，已验证）
```python
from vision_core import ask_vision
result = ask_vision(
    "image.png",
    prompt="描述图片内容",
    session=session,      # 或 cfg=cfg_dict / cfg_name="配置名"
)
```
签名：
```python
ask_vision(image_input, prompt=None, timeout=60, max_pixels=1440000, *, session=None, cfg=None, cfg_name=None, max_retries=0) -> str
```
说明：
- 支持 `str/Path/PIL.Image`
- 统一构造 Claude `image(base64)` block，优先复用 `raw_ask/make_messages` 转换链
- 若传入 wrapper client，会自动解包到 `.backend`
- 成功返回模型文本，失败统一 `Error: ...`
- 已独立验证：`import vision_core`、`import tests.test_vision_core`、`python -m unittest tests.test_vision_core -v`

## 核心参数
- `image_input`: 文件路径(str/Path) 或 PIL Image 对象
- `prompt`: 提示词（默认：详细描述这张图片的内容）
- `max_pixels`: 最大像素数（默认1440000，超则自动缩放）
- `timeout`: 超时秒数（默认60）

## 故障排除
| 问题 | 解决方案 |
|------|--------|
| 导入失败 | 可检查 `../../mykey.py` 文件是否存在（仅检查存在性，不读取内容） |
| 超时 | 提高 timeout 或降低 max_pixels |
| 格式错误 | 确保使用 PIL 支持的格式（PNG/JPG/GIF等） |

## 关键风险与坑点 (L3 Caveats)
- **无重试机制**: `vision_api.py` 内部未实现 API 错误重试（如 503、超时）。在自动化流程中使用时，**必须在上层代码手动实现重试逻辑**（建议指数退避），否则偶发网络波动会导致任务直接崩溃中断。
- **本地封装验证范围**: `vision_core.py` 这次任务只独立验证了导入、消息构造/调用路径与 mock 单测；**未验证真实线上视觉后端是否可用**。接真实接口时仍需自备可用 `session/cfg/cfg_name`。
- **API Config**: 当前使用 `claude_config141`(ncode.vkm2.com, 已验证)。备选可用: `native_claude_config2/84/5535`。失效时直接改 `vision_api.py` 中的 `cfg = mk.claude_configXXX`。

---
更新: 2025-07-18 | 修复oai_config导入+返回值统一str
更新: 2026-02-18 | 默认后端改为Claude原生API | SOP精简(删废话/水段/合并示例)
更新: 2026-07 | 修复config(原claude_config8不存在)→改为claude_config141
