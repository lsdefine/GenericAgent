# Codex Instructions for GenericAgent

这是 Codex 原生识别的项目指令文件。

## 本地边界

- 这个 checkout 是上游 GenericAgent 源码 + 本机外挂配置。
- 默认不要修改 GA 原生源码，除非用户明确要求。
- slash commands、nmem、bot 启动包装等本地增强优先放 `local_ga/`、ignored `memory/` 或外部 wrapper，不要写进 GA core source。
- `.omx/` 只属于 Codex/OmniCodex 工作层；不要让 GA runtime 把 `.omx/` 当作自己的能力来源。
- 不要把 `.omx/`、密钥、cookie、运行态会话写进 Git。
- `local_ga/` 默认是本地外挂；只有用户明确要发布 wrapper 时才纳入提交。

## 当前本地扩展

- nmem session 自动同步 hook：`.omx/ga_nmem_hook/`
- 本地 slash command wrapper：`local_ga/`
- 本地规则说明：`.omx/local_docs/`
- 本地手册：`GENERIC_AGENT_HANDBOOK.md`
- 本机运行说明：`RUNBOOK_LOCAL.md`
- 本地 KB：`kb/`

## 输出要求

完成任务时说明：

- 是否改了 GA 原生源码；
- 是否只改了本地外挂；
- 做了什么验证；
- 后续 `git pull` 是否可能冲突。
