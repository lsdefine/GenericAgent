# R121: Hermes CLI盲区探测报告

**日期**: 2026-06-06 | **类型**: 探测/评估 | **状态**: 完成

## 概览

Hermes Agent v0.15.1 提供 **46+ 个子命令**，此前仅使用 `chat` 和 `model`。
本次探测覆盖所有子命令的 help 文档 + 实际运行验证关键命令。

## 子命令全景（按集成价值分类）

### 🟢 高价值 — 立即集成
| 命令 | 功能 | 集成建议 |
|------|------|---------|
| `status` | 显示组件/API Key/环境状态 | 替代手动检查 .env/provider |
| `sessions list/stats` | 查看会话列表/统计 | 可集成到health_dashboard |
| `logs` | 查看/tail agent日志 | 调试用，比直接读文件方便 |
| `config show` | 展示配置 | 了解当前模型/provider |
| `doctor --fix` | 诊断+自动修复 | 环境故障时第一响应 |

### 🟡 中价值 — 按需使用
| 命令 | 功能 | 使用场景 |
|------|------|---------|
| `cron` | 定时任务管理 | 与scheduler有重叠，可互补 |
| `skills list/search` | 技能管理 | 探索可安装的第三方skill |
| `tools list/enable` | 工具开关控制 | CLI/Telegram各平台工具管理 |
| `gateway status` | 消息网关状态 | Telegram/Discord集成状态 |
| `memory status` | 外部记忆提供者 | 当前内置记忆，可扩展 |
| `mcp list` | MCP服务器列表 | Agent互操作性 |
| `proxy start` | 本地OpenAI代理 | 第三方工具接入OAuth provider |
| `update` | 更新hermes | 版本落后204commits需更新 |
| `backup` | 备份hermes配置 | 定期备份 |

### 🔵 探测性 — 感兴趣但暂不集成
| 命令 | 功能 | 说明 |
|------|------|---------|
| `dashboard` | Web UI (port 9119) | 替代TUI的可视化方案 |
| `portal` | Nous Portal集成 | 模型/工具网关 |
| `kanban` | 协作看板 | 多profile任务协作 |
| `webhook` | 动态webhook订阅 | 外部事件触发agent |
| `send` | 发送消息到平台 | 脚本/CI中调用agent |
| `acp` | Agent Client Protocol | Agent互操作标准 |
| `insights` | 使用洞察 | 暂未了解详情 |

### ⚪ 低价值 — 当前不适用
`migrate`, `secrets`, `lsp`, `whatsapp`, `slack`, `pairing`, 
`bundles`, `plugins`, `curator`, `computer-use`, `claw`,
`completion`, `desktop/gui`, `prompt-size`, `dump`, `debug`,
`security`, `checkpoints`, `import`, `uninstall`

## 验证的关键发现

### `hermes status --all`
- 当前模型: deepseek-v4-flash
- Provider: OpenCode Go
- API Keys: OpenAI ✓, DeepSeek ✓, OpenRouter ✗
- 环境: ✓ .env存在

### `hermes doctor`
- 支持 `--fix` 自动修复问题
- 支持 `--ack ADVISORY_ID` 确认安全建议

### `hermes cron`
- 独立于sche_tasks的定时任务系统
- 支持create/edit/pause/resume/remove
- 有 `tick` 命令手动触发检查

### `hermes sessions list`
- SQLite存储的会话记录
- 可export为JSONL

### `hermes gateway`
- 支持Telegram/Discord/WhatsApp/Weixin
- 可安装为systemd服务

## 集成建议（优先级排序）
1. **高**: `hermes status` → 整合到health_status报告管线
2. **高**: `hermes update` → 版本落后204 commits，建议更新
3. **中**: `hermes sessions list/stats` → 补充到dashboard
4. **中**: `hermes logs` → 调试脚本中替代cat
5. **低**: `hermes cron` → 评估是否替代sche_tasks

