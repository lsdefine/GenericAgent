# Subagent 调用 SOP

## Task Mode 文件IO协议

- 目录：`temp/{task_name}/`（相对代码根），主agent cwd在temp/时即 `./{task_name}/`
- 启动：`python agentmain.py --task {name} [--input "内容"] [--bg] [--llm_no N]`（cwd=代码根）
  - `--input`：自动建目录+清旧output+写input.txt
  - `--bg`：自举后台（Popen自身去掉--bg → print PID → exit）
- 流程：启动 → 轮询 output.txt（`[ROUND END]`=该轮完成）→ 写 reply.txt 继续 → 不写则5min退出
- output1/2/3.txt：reply后各轮输出（递增编号），同样append+`[ROUND END]`
- input.txt：目标+约束，可指定SOP名。禁写具体步骤（除非已读SOP确认）。大量数据给路径禁塞入
- --bg启动瞬间返回，可同一code_run内sleep后poll；非--bg方式禁止合并启动+轮询

```python
pid = os.popen(f'python {agent_root}/agentmain.py --task {name} --input "{prompt}" --bg').read().strip()
```

## 场景1：测试模式 - 行为验证
**用途**：观察agent真实行为，修正RULES/L2/L3/SOP
**流程**：创建test_path/写input.txt→启动subagent→轮询output.txt(2秒间隔)→验证→清理重复
**测试原则**：只给目标，不提示位置/不诱导做法，观察自主选择
**修正闭环**：发现问题→设计测试→定位根源(RULES/L2/L3/SOP)→patch修正→验证
**技术要点**：Insight优先级>SOP；subagent的cwd=temp/
**两种测试**：
- 测SOP质量：input指定SOP名（如"用ezgmail_sop查看最近3封未读邮件"），排除导航干扰，失败即SOP问题
- 测导航能力：input只写目标，验证subagent能自主从insight找到正确SOP。禁止内联SOP内容

## 场景2：Map模式 - 并行处理
**用途**：将N个独立同构子任务分发给各自的subagent处理
**核心优势**：独立上下文。避免处理文档A的长上下文污染处理文档B的质量
**约束**：
- 文件系统共享是优点：不同agent处理不同输入文件，产生不同输出文件
- 共享资源冲突：键鼠不可共享；浏览器暂时不可并行使用，避免同时操作同一标签页
- 不满足map模式的任务 → 主agent顺序执行即可，别用subagent
**标准流程（map-reduce）**：
1. 主agent准备阶段：爬取/dump数据，存为多个独立输入文件
2. 分发：对每个文件启动一个subagent处理（主agent自己也可以处理其中一个）
3. 收集：等所有subagent完成，主agent读取各输出文件，汇总结果

## subagent内部plan_mode使用
**原则**：subagent本身是完整agent，接收多步骤任务时应在内部创建plan管理执行
**触发条件**:任务包含3个以上子步骤、子步骤之间有依赖关系、需要checkpoint来恢复执行
**实现方式**：
1. **主agent创建subagent时**：在input.txt中说明任务包含多个步骤，建议使用plan_mode
2. **subagent内部执行**：检测到多步骤任务后，创建 `./subagent_plan.md` 并使用plan_mode执行
3. **主agent监控**：只关注最终结果（output*.txt），不需要关心subagent内部如何执行
4. **文件传递机制**：主agent创建subagent时在task_dir中生成 `context.json`，包含所有文件的**绝对路径**
   **⚠ subagent启动后第一步必须读取context.json**
   **⚠ 所有文件操作必须使用context.json中的绝对路径**
**格式示例**：
```json
{
  "task": "任务描述",
  "work_dir": "/absolute/path/to/plan_dir/",
  "input_files": {
    "paper_info": "/absolute/path/to/paper_info.txt"
  },
  "output_files": {
    "pdf": "/absolute/path/to/paper.pdf",
    "report": "/absolute/path/to/paper_report.md"
  },
  "dependencies": ["paper_info.txt必须存在"]
}
```