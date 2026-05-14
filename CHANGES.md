# 变更说明

## Pull Request 说明

**目标分支：** `master`  
**涉及文件：** `frontends/stapp2.py`、`launch.pyw`

**合并前检查：**
- [ ] 底部输入区：`+` 上传按钮与聊天框水平对齐（包括 600 px 窄 webview 窗口）
- [ ] Ctrl+V 粘贴截图：缩略图显示，可删除，发送后附加到消息
- [ ] `python launch.pyw` 正常弹出 GenericAgent 窗口

---

## 新增功能

### 文件上传

输入区左侧新增 `+` 图标按钮，点击可上传任意类型文件。

- **缩略图预览**：图片显示缩略图，其他文件显示类型图标，支持点击 `×` 删除
- **附件注入**：发送时自动将文件信息追加到 prompt
  - 图片：磁盘路径 + base64（供 vision API 使用）
  - 文本文件（`.txt .md .py .json` 等）：内联最多 6000 字符
  - 其他：仅磁盘路径，Agent 可用 `file_read` 工具读取
- 文件保存至 `temp/uploaded/<timestamp>_<name>`，发送后清空队列

### 截图粘贴

在聊天框聚焦时，Ctrl+V 粘贴剪贴板图片直接入队，无需手动保存文件。

实现方式：页面注入 JS 监听 `paste` 事件，捕获 `image/*` 内容转为 base64，通过隐藏信号输入框触发 Streamlit rerun，Python 侧解码后与上传文件走同一处理流程。

---

## 修改要点

- `launch.pyw`：启动目标切换为 `stapp2.py`；新增 `window = None` 初始化防止 idle monitor 在窗口就绪前崩溃；webview 启动等待时间调整为 5 秒
