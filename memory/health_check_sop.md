# Agent Health Check SOP

## 何时使用

当以下情况出现时，使用 health 工具审计 GenericAgent 自身：

- 模型表现突然变差（回答质量下降、工具调用不稳定）
- 记忆污染（旧话题泄漏到新对话）
- 输出格式损坏（渲染层变异）
- 长时间运行后出现不稳定行为
- 新增功能后原有能力退化
- 用户怀疑系统提示词或记忆层有冲突

## 如何使用

### 方式 1: Agent 自主调用

在对话中说：
```
请运行 health 工具审计当前系统状态
```

### 方式 2: 手动运行

```bash
python3 memory/agent_health_check.py --target-dir /path/to/GenericAgent
```

### 方式 3: JSON 输出（供后续分析）

```bash
python3 memory/agent_health_check.py --json
```

## 审计模式

| 模式 | 检查内容 | 耗时 |
|------|---------|------|
| full | 全量审计（默认） | ~200ms |
| wrapper | 仅审计 wrapper 层（系统提示词、配置、agent loop） | ~100ms |
| memory | 仅审计记忆/上下文层 | ~100ms |
| tools | 仅审计工具层 | ~50ms |
| rendering | 仅审计渲染/传输层 | ~50ms |

## 严重度模型

| 级别 | 含义 |
|------|------|
| critical | 能导致 agent 产生完全错误的行为 |
| high | 频繁损害正确性或稳定性 |
| medium | 正确性通常保持，但输出脆弱或浪费 token |
| low | 主要是装饰性或维护性问题 |

## 审计维度

1. **system_prompt** — 系统提示词冲突、过长、工具约束仅在文字中
2. **config** — API key 硬编码、多 provider 无 fallback
3. **memory** — L1 超行、L4 积累、文件间重复内容
4. **tools** — schema 无效、实现缺失、超时未设
5. **agent_loop** — 无限制重试、无最大轮次限制
6. **context_dup** — 同一信息通过多层重复注入
7. **rendering** — JS 注入可能变异输出
8. **hidden_agent** — 隐藏的自动触发任务、前端中的直接 LLM 调用

## 修复建议优先级

1. 先修 critical → 阻断性错误
2. 再修 high → 频繁损害
3. 最后修 medium/low → 优化项

修复后重新运行 health 验证。

## 定期运行

建议每周运行一次 full 模式：
```bash
python3 memory/agent_health_check.py --mode full
```
