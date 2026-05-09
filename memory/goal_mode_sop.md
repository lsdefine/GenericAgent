# Goal Mode SOP

## 何时使用

用户给出开放目标 + 时间预算（如"花3小时持续优化X"、"没事也找事干"），且不是一次性闭环任务。

## 设置

写 `temp/goal_state.json`（或自定义路径）：

```json
{
  "objective": "用户原话目标",
  "budget_seconds": 10800,
  "start_time": <time.time()>,
  "turns_used": 0,
  "max_turns": 200,
  "status": "running"
}
```

- `budget_seconds`：最少 3 小时（10800），按用户要求调整
- `max_turns`：防空转上限，一般 200 够用
- `status`：必须为 `"running"`

## 启动

必须后台启动（长时间运行，不占前台终端）：

```bash
# 默认路径 temp/goal_state.json
start /b python agentmain.py --reflect reflect/goal_mode.py

# 自定义路径（多实例）
set GOAL_STATE=temp/goal_xxx.json && start /b python agentmain.py --reflect reflect/goal_mode.py

# 用其他模型跑（--llm_no 选择已配置的第N个LLM，从0开始）
set GOAL_STATE=temp/goal_xxx.json && start /b python agentmain.py --reflect reflect/goal_mode.py --llm_no 1
```

## 停止

- 预算耗尽时自动进入收口轮，然后停止
- 手动停：杀进程

## 观察进度

- 状态：读 goal_state.json 的 `turns_used` / `status`
- 详情：看 `temp/model_responses/` 下最近修改的文件尾部
