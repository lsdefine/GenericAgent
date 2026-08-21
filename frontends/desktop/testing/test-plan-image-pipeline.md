# 图片管线测试方案

## 状态: 🔄 进行中

## 测试目标

验证图片从粘贴/选择到 LLM 实际接收并理解的完整管线：
- 前端 Composer → 上传 → Bridge → Agent → LLM API

## 架构层次

```
[Composer]           processFiles → FileReader.readAsDataURL → AttachmentFile{status:'ready', preview:dataUrl}
     ↓ handleSend
[services/chat.ts]   sendPrompt → POST /upload (获取磁盘路径) → POST /session/{sid}/prompt {imageMetas}
     ↓
[desktop_bridge.py]  submit_prompt → image_paths → run_agent_turn(sess, prompt, image_paths)
     ↓              _patch_chat_for_images: monkey-patch llmclient.chat
[agentmain.py]       put_task(prompt) → run() → agent_runner_loop(client, ..., raw_query)
     ↓              （agentmain 不传 images — 由 patch 注入）
[llmcore.py]         NativeToolClient.chat → 用户消息 content 变为 [text, image_block]
     ↓              过滤器保留 type!="text" 的块
[NativeXxxSession]   raw_ask → API 请求 (Claude/OAI 自动格式转换)
```

## 关键修复点

1. **frontends/desktop_bridge.py:_patch_chat_for_images** — 绕过 agentmain 和 llmcore 的限制
   方案: monkey-patch `backend.ask`（在 `NativeToolClient.chat` 的 filter 之后注入）
   - 注入点在 filter 下游，直接修改传给 session 的 merged msg 的 content list
   - `del backend.ask` 恢复原始（MixinSession 通过 `__getattr__` 回退到 `_sessions[0].ask`）
   - 只拦截首次调用，后续轮次不受影响

**约束:** agentmain.py / llmcore.py / agent_loop.py 等后端文件一律不可修改

## 测试矩阵

### 单元测试（无需 LLM 调用）

| # | 测试点 | 断言 |
|---|--------|------|
| U1 | `NativeToolClient.chat` 过滤器保留 image 块 | content 含 `type:"image"` 块经过 filter 后仍在 |
| U2 | `_patch_chat_for_images` 正确注入且只触发一次 | 第一次调用注入 image blocks，第二次恢复原始 |
| U3 | `_patch_chat_for_images` 对 ToolClient 无效（跳过） | 非 NativeToolClient 不 patch |
| U4 | `_msgs_claude2oai` 转换 Claude image → OAI image_url | 正确产出 `data:mime;base64,...` |
| U5 | `_fix_messages` 保留 image 块 | user message 中 image block 不被丢弃 |

### 集成测试（需要 Bridge 运行）

| # | 测试点 | 验证方法 |
|---|--------|----------|
| I1 | POST /upload 接收 base64 返回路径 | 文件存在于 desktop_uploads/ |
| I2 | POST /session/{sid}/prompt 带 imageMetas | 不报错，agent 开始运行 |
| I3 | LLM 实际接收 image 内容 | 检查 model_responses log 中 content 含 image block |
| I4 | 前端 UserMessage 显示图片 | data: URL 直接渲染 |

### E2E 冒烟测试（手动）

| # | 操作 | 预期 |
|---|------|------|
| E1 | Cmd+V 粘贴截图 → 发送 | 模型回复中提到图片内容 |
| E2 | 拖放 .png 文件 → 发送 | 同上 |
| E3 | Context Menu → 选择图片 → 发送 | 同上 |
| E4 | 粘贴图片 + 文字混合 | 模型回复同时涉及文字和图片 |
| E5 | 多张图片同时发送 | 所有图片都被识别 |

## 自动化集成测试脚本

路径: `frontends/desktop/testing/test_image_pipeline.py`

该脚本通过 HTTP API 调用 bridge，模拟完整的图片上传 + 发送流程，验证:
1. 上传成功（文件落盘）
2. prompt 带图片提交成功
3. LLM 日志中包含 image block（证明图片送达 API）

## 回归风险

- 多轮对话中 image block 在 history 中累积（正常行为，但大图可能占 token）
- MixinSession fallback 时 patch 是否跟随正确 session
- ToolClient 后端（非 Native）无法传图 — 需明确降级提示
