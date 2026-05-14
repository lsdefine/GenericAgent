# 变更说明：stapp2 二次开发功能整合

## Pull Request 说明

**目标分支：** `master`  
**源分支：** `master`（当前本地 2 commits ahead of `origin/master`）  
**涉及提交：**
- `2cf9c1f` feat(ui): 对齐 Origin stapp.py 外观风格，保留上传/粘贴功能
- `b05eabc` fix: upload row layout in narrow webview + launch.pyw robustness

**改动文件：**
- `frontends/stapp2.py`（主前端，+97 / -634 行）
- `launch.pyw`（桌面启动器，+17 / -2 行）

**合并前检查：**
- [ ] `streamlit run frontends/stapp2.py` 正常启动，页面显示"🖥️ Cowork"标题
- [ ] 侧边栏展开后出现"强行停止任务 / 重新注入工具 / 🐱 桌面宠物 / 自主行动"区
- [ ] 右上角汉堡菜单可见（System / Light / Dark 可切换）
- [ ] 底部输入区：`+` 上传按钮与聊天框水平对齐（包括 600 px 窄 webview 窗口）
- [ ] Ctrl+V 粘贴截图正常工作，缩略图显示，可删除
- [ ] `python launch.pyw` 正常弹出 GenericAgent 窗口

---

## 一、背景

本次改动在 upstream/main 最新代码基础上，将本地 `stapp2.py` 的二次开发成果整合进来，并同步将前端外观对齐至 Origin (`GA-Origin/GenericAgent/frontends/stapp.py`) 的视觉风格。

Origin 版本外观参考：`frontends/example/GA1.jpg`（主界面）、`GA2.jpg`（侧边栏）、`GA3.jpg`（汉堡菜单）。

---

## 二、`frontends/stapp2.py` 改动详情

### 2.1 主题 CSS 精简

**旧：** `ANTHROPIC_CSS` 约 630 行，覆盖页面背景（暖棕 `#FAF9F6`）、侧边栏底色（`#F0EDE4`）、所有按钮/输入框/链接颜色，并隐藏汉堡菜单（`#MainMenu { display:none }`）。

**新：** `ANTHROPIC_CSS` 缩减至仅 `:root {}` CSS 变量定义（约 20 行），保留颜色常量供 `FILE_UPLOAD_CSS` 引用，不再覆盖任何页面元素。

**效果：** 页面恢复 Streamlit 默认白/浅灰主题；右上角汉堡菜单重新可见（System / Light / Dark 主题切换）。

### 2.2 CSS 注入精简

移除了以下注入（功能已不需要或与新风格冲突）：
- `build_dynamic_font_css(110.0)` — 字体缩放脚本
- `ANTHROPIC_SELECTBOX_SCRIPT` — 备用链路选择框宽度自适应脚本
- `build_header_agent_badge_script()` — 页眉 Agent 名称徽标脚本

保留：
```python
st.markdown(ANTHROPIC_CSS, unsafe_allow_html=True)       # 仅 :root 变量
st.markdown(FILE_UPLOAD_CSS, unsafe_allow_html=True)      # 上传按钮 + 缩略图样式
st.markdown(PASTE_HIDDEN_INPUT_CSS, unsafe_allow_html=True)
_embed_html(build_paste_listener_script(), height=0, width=0)
```

### 2.3 页面标题

在 CSS 注入之后、欢迎消息之前添加：
```python
st.title("🖥️ Cowork")
```
与 Origin stapp.py 第 51 行保持一致。

### 2.4 侧边栏重写（`render_sidebar()`）

对齐至 Origin stapp.py 第 56–111 行的完整版本，新增以下控件：

| 控件 | 功能 |
|------|------|
| LLM Core 说明文字 | `st.caption(f"LLM Core: {当前LLM名称}")` |
| 折叠式 LLM 选择框 | 切换后立即 `agent.next_llm()` + `st.rerun()` |
| **强行停止任务** | `agent.abort()` 发送停止信号 |
| **重新注入工具** | 清除 `last_tools` 缓存并从 `tool_usable_history.json` 重新注入工具历史 |
| **🐱 桌面宠物** | 启动 `desktop_pet_v2.pyw`，注册 `_turn_end_hooks['pet']` 在每轮结束时推送摘要 |
| **自主行动区** | "开始空闲自主行动"（将 `last_reply_time` 回拨 1800 秒）、"允许/禁止自主行动"切换、状态说明文字 |

新增 import（放在文件顶部）：
```python
import subprocess
from urllib.request import urlopen
from urllib.parse import quote
script_dir = os.path.dirname(os.path.abspath(__file__))
```

新增 I18N 支持（`set_page_config` 之后）：
```python
LANG = os.environ.get('GA_LANG', 'zh')
I18N = { 'zh': {...}, 'en': {...} }
def T(key): return I18N.get(LANG, I18N['zh']).get(key, key)
```

---

## 三、新增功能：文件上传

### 3.1 上传按钮 UI

`FILE_UPLOAD_CSS` 将 Streamlit 原生 `st.file_uploader` 改造为极简 `+` 图标按钮（48×48 px，圆角 12 px），隐藏拖放说明区，悬停变为 Anthropic 橙色。

输入区布局（`frontends/stapp2.py:1028`）：
```python
col_upload, col_input = st.columns([0.08, 0.92])
```
- 左列：`st.file_uploader`（渲染为 `+` 按钮）
- 右列：`st.chat_input`

### 3.2 窄窗口水平对齐修复

webview 窗口宽 600 px，侧边栏约 200 px，主内容区约 380 px。8% 列宽约 30 px 小于按钮 min-width 48 px，导致 flexbox 换行堆叠。

修复方式（`FILE_UPLOAD_CSS` 末尾）：
```css
[data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) {
    flex-wrap: nowrap !important;
    align-items: flex-end !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) > *:first-child {
    flex: 0 0 54px !important;
    min-width: 54px !important;
    max-width: 54px !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) > *:last-child {
    flex: 1 1 0 !important;
    min-width: 0 !important;
}
```

### 3.3 文件处理逻辑

| 函数 | 位置 | 功能 |
|------|------|------|
| `save_uploaded_file(file_dict)` | `:439` | 保存文件到 `temp/uploaded/<timestamp>_<name>`，返回绝对路径 |
| `generate_thumbnail(file_dict)` | `:457` | 图片用 Pillow 缩放为 80×80 base64；非图片返回 emoji 图标 |
| `render_file_thumbnails()` | `:537` | 渲染缩略图卡片行，每张卡片含 `×` 删除按钮（通过隐藏信号输入框触发） |
| `build_prompt_with_files(prompt, files)` | `:490` | 构建发给 Agent 的提示：图片含磁盘路径+base64 截断；文本文件内联最多 6000 字符；其他文件仅路径 |

文件在用户发送消息时通过 `build_prompt_with_files` 附加到 prompt，随后清空 `uploaded_files` 列表并重置 `file_uploader_key` 刷新上传控件。

---

## 四、新增功能：截图粘贴

### 4.1 信号机制

使用两个隐藏的 `st.text_input` 作为 JS → Python 的信号通道：

| 信号输入框 | placeholder | 作用 |
|-----------|------------|------|
| `paste_image_signal` | `__paste_image_signal__` | 接收粘贴图片的 base64 data URI |
| `delete_file_signal` | `__delete_file_signal__` | 接收要删除的文件索引 |

`PASTE_HIDDEN_INPUT_CSS` 用 `position: fixed; left: -99999px` 将这两个输入框移出可见区，并将其 Streamlit 容器高度设为 0，避免占据布局空间。

### 4.2 粘贴监听 JS（`build_paste_listener_script()`，`:744`）

注入到父 `window`（Streamlit 主框架）的 `paste` 事件监听器：
1. 检测剪贴板 items 中是否有 `image/*` 类型
2. 用 `FileReader.readAsDataURL` 转为 base64
3. 通过 React 原生 setter 写入 `__paste_image_signal__` 输入框
4. 触发 `input` → `blur` → `focusout` 事件链，驱动 Streamlit rerun

幂等保护：`window.__pasteImageListenerInstalled__` 标志位防止重复注入。

### 4.3 Python 侧处理（`:979`）

```python
_paste_val = st.session_state.get("paste_image_signal", "")
if _paste_val and _paste_val.startswith("data:image"):
    # 解码 base64 → bytes，构造 file_dict，追加到 uploaded_files
    st.session_state.paste_image_signal = ""
```

粘贴的图片以 `paste_<timestamp>.png` 命名，与手动上传的文件走同一 `render_file_thumbnails()` + `build_prompt_with_files()` 流程。

---

## 五、`launch.pyw` 改动

| 改动 | 原因 |
|------|------|
| Streamlit 目标从 `stapp.py` → `stapp2.py` | 切换到二次开发版前端 |
| 移除 `--client.toolbarMode viewer` | 恢复汉堡菜单可见 |
| `window = None` 模块级初始化 | 防止 `idle_monitor` 在窗口创建前访问 `window` 报 `NameError` |
| `time.sleep(5)` 启动等待 | 给 Streamlit 足够启动时间再创建 webview 窗口 |
| `idle_monitor` 初始 `time.sleep(12)` | 避免在页面加载完成前执行 JS |
| `idle_monitor` 首行增加 `if not window` 守卫 | 短路跳过未初始化阶段 |
| `webview.start()` 包裹 `try/except` + 诊断打印 | 捕获并显示 webview 异常，便于调试 |
