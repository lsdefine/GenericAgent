# 导入记忆与会话：可恢复覆盖契约

## 调用边界

React 通过原生目录选择器取得路径，只向包内 bridge 发送：

```http
POST /memory/import
Content-Type: application/json

{"sourceDir":"/path/to/source"}
```

源目录中的代码永不执行。目标始终是当前有效 `GA_ROOT`。

## 文件语义

| 数据 | 源 | 目标 | 规则 |
| --- | --- | --- | --- |
| memory | `memory/**` | `<GA_ROOT>/memory/**` | 先备份整个现有 memory，再覆盖同名文件并补齐新文件 |
| responses | `temp/model_responses/**` | `<GA_ROOT>/temp/model_responses/**` | 只补缺；同名文件跳过，不覆盖 |
| sessions | `temp/desktop_sessions/*.json` 及旧单文件 | 当前 session store | 按 session id 去重，只持久化新增项；忽略内部 `tui_*` 会话 |

备份目录为 `<GA_ROOT>/temp/memory_import_backup_<timestamp>/memory`。只要目标 memory
原先非空且本次导入包含 memory，`backupDir` 必须指向可恢复的完整备份。

## 响应

```json
{
  "ok": true,
  "memoryCopied": 3,
  "responsesCopied": 5,
  "responsesSkipped": 2,
  "sessionsAdded": 4,
  "sessionsSkipped": 1,
  "sessionsFileFound": true,
  "backupDir": "/path/to/temp/memory_import_backup_20260821_120000"
}
```

这些字段是公共接口，不得更名或改成仅供 UI 展示的字符串。

## 与连接本地核心的区别

- 导入是一次性文件操作，不重启 bridge、不改变 `GA_ROOT`。
- 连接只改变有效数据根，不复制 memory、responses 或 sessions。
- 导入接受只有 memory 或 responses 的目录；连接要求 `agentmain.py` 并通过 compatibility
  probe。

## 必测场景

- 同名 memory 被新内容覆盖，旧内容可从 `backupDir` 恢复。
- 同名 response 保持旧内容并计入 `responsesSkipped`。
- 重复 session id 不新增，内部 `tui_*` session 不进入 Desktop。
- 源等于目标、源为空、复制失败和 bridge 离线均明确失败。
- 使用隔离的发布包副本验证真实文件结果，测试结束不污染用户数据。
