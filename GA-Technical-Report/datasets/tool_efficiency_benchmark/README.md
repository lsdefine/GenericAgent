# 工具使用效率评测数据集

本目录整理了维度 4 工具使用效率评测报告中实际使用的 16 条 benchmark 任务。该数据集只包含任务定义、输入资产和 grader，不包含历史运行结果、模型输出、token 统计或工具调用轨迹。

## 文件结构

- `tool_efficiency_tasks.jsonl`：任务数据，每行是一个 JSON 对象。
- `assets/`：任务所需的本地输入资产，按 `task_id` 分目录存放，共 21 个文件。
- `graders/`：从原始 benchmark 任务目录复制出的 Python 自动评估脚本。

## 任务数量

| 任务类型 | 数量 | 来源 |
|---|---:|---|
| `simple` | 11 | 报告中使用的 `benchmark/tools_task` 简单工具任务 |
| `long_horizon` | 5 | 报告中使用的 `benchmark/tasks` 长程任务 |
| 合计 | 16 | - |

## JSONL 字段说明

| 字段 | 类型 | 含义 |
|---|---|---|
| `task_id` | string | 数据集内任务唯一标识，使用 `teb_01` 到 `teb_16` 的连续编号。 |
| `original_task_id` | string | 原始 benchmark 任务目录名，用于追溯原始任务来源。 |
| `task_type` | string | 任务类型，取值为 `simple` 或 `long_horizon`。 |
| `source_suite` | string | 任务来源或设计参照；简单任务对应 `claude_code` 或 `openclaw`，长程任务对应 `dimension4_long`。 |
| `target_tool_or_capability` | string | 该任务希望覆盖或对照的 baseline 工具/能力。 |
| `prompt` | string | 交给 agent 执行的任务指令。 |
| `assets` | list[string] | 任务需要的本地输入资产路径，路径相对于当前数据集目录；如果没有额外输入资产则为空列表。 |
| `expected_outputs` | list[string] | 期望生成的输出文件；对于直接回答型简单任务，使用 `final_response` 表示最终回答。 |
| `grader` | string or null | 对应的自动评估脚本路径，路径相对于当前数据集目录。 |

## 资产说明

简单工具任务的输入资产来自原始 `benchmark/tools_task/<task_id>` 目录中除 `task.md` 和 `grader.py` 之外的文件。

长程任务的本地输入资产来自 `benchmark/assets/<task_id>`，而不是 `benchmark/tasks/<task_id>`。5 个长程任务中：

| 任务 | 本地输入资产 | 说明 |
|---|---:|---|
| `task_04_paper_ppt_generation` | 无 | 依赖公开论文页面和 PDF，输出 PPT 与说明文件。 |
| `task_05_sql_copilot_query_generation` | 有 | 包含 `analytics.db`、`schema.md` 和数据库生成脚本。 |
| `task_06_experiment_analysis_report_generation` | 有 | 包含实验分析所需的 CSV 数据文件和数据生成脚本。 |
| `task_07_text_api_procurement_decision` | 无 | 依赖公开 API 价格页面，输出成本对比和决策 JSON。 |
| `task_09_dapo_reproduction_feasibility` | 无 | 依赖公开论文、项目页和代码仓库，输出可行性判断 JSON。 |

## 注意事项

本数据集只保留最终报告中实际使用的任务，不包含早期候选任务。运行产物如 `run_summary.json`、`tool_trace.jsonl`、`final_response.txt`、token 统计等均未纳入本目录。
