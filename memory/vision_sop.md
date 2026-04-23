# Vision SOP

> ⚠️ **状态说明 (2026-04-22)**：`vision_api.py` 已从template创建并适配。可用后端: openai(gpt-5.4 via native_oai_config, 已验证vision✅)。Claude后端暂不可用(缺config)。当前可用视觉能力：vision_api.py(云端VLM) + ocr_utils.py(本地OCR) + ui_detect.py(YOLO UI检测)。

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

## 如果没有 `vision_api.py`，初次构建vision能力

1. 复制 `memory/vision_api.template.py` → `memory/vision_api.py`
2. 只改头部"用户配置区"：去 `mykey.py` 里扫描变量名（⚠️ 只看名字，禁止输出 apikey 值），尝试找能用配置名填入 `CLAUDE_CONFIG_KEY` / `OPENAI_CONFIG_KEY`，`DEFAULT_BACKEND` 选后端，并测试
3. 保底：没有可用 config 时去 `https://modelscope.cn/my/myaccesstoken` 申请 token 填入 `MODELSCOPE_API_KEY`

## 故障排除
| 问题 | 解决方案 |
|------|--------|
| 导入失败 | 可检查 `../../mykey.py` 文件是否存在（仅检查存在性，不读取内容） |
| 超时 | 提高 timeout 或降低 max_pixels |
| 格式错误 | 确保使用 PIL 支持的格式（PNG/JPG/GIF等） |

## 关键风险与坑点 (L3 Caveats)
- **无重试机制**: `vision_api.py` 内部未实现 API 错误重试（如 503、超时）。在自动化流程中使用时，**必须在上层代码手动实现重试逻辑**（建议指数退避），否则偶发网络波动会导致任务直接崩溃中断。
- **API Config**: 当前使用 `claude_config141`(ncode.vkm2.com, 已验证)。备选可用: `native_claude_config2/84/5535`。失效时直接改 `vision_api.py` 中的 `cfg = mk.claude_configXXX`。
- **OpenAI-compatible 空响应排查**: 先看原始 `choices[0].message.content`。`content` 为数组不等于空；当前解析链对数组 content 兼容性一般，可能返回结构化块而非纯字符串。真正空结果更接近 `content=[]` 或 `None`。
- **空 prompt 边界**: OpenAI-compatible vision 下，空 `prompt` 会直接得到 `HTTP 400`，这属于非法请求，不应误判为模型“空响应”。

---
更新: 2026-04-23 | 补充OpenAI-compatible vision空响应排查边界
更新: 2025-07-18 | 修复oai_config导入+返回值统一str
更新: 2026-02-18 | 默认后端改为Claude原生API | SOP精简(删废话/水段/合并示例)
更新: 2026-07 | 修复config(原claude_config8不存在)→改为claude_config141
更新: 2026-04-17 | 标注vision_api.py缺失+补充ui_detect.py文档+阻塞项说明

## ui_detect.py — YOLO UI元素检测（当前可用）

> 位于 `memory/ui_detect.py`，基于OmniParser YOLO模型。依赖: ultralytics, rapidocr-onnxruntime, pillow, numpy

| 函数 | 用途 |
|------|------|
| `detect_ui_elements(image_path, model_path=None, conf=0.25)` | 检测UI元素，返回 `[{bbox, confidence, class}]` |
| `ocr_text(image_path)` | RapidOCR文本识别，返回 `[{text, bbox, confidence}]` |
| `visualize(image_path, detections, ocr_results=None, output_path=None)` | 可视化标注，返回PIL Image |

- CLI: `python ui_detect.py <图片> [模型路径] [输出路径]`
- 模型默认路径: `temp/weights/icon_detect/best.pt`
