# 自主行动 SOP (v2 — Closed Loop 升级)
**触发**：需要云曦自主执行长期/无人值守任务时
**禁用**：用户明确要求立即响应的交互式任务

## Loop Contract（启动前必须执行）

**任何自主任务必须先建立 Loop Contract，填 [loop_contract_template.md]：**
- TRIGGER（触发条件） | SCOPE（作用范围）| ACTION（具体行为）| BUDGET（预算红线）| STOP（停止条件）| REPORT（上报通道）
- 若不填，默认使用以下硬约束：
  - BUDGET: 最大30轮 | 最大60分钟 | 最大3个子Agent
  - STOP: 连续失败3次 → 熔断器跳闸 | CPU 高+I/O停滞60s → 看门狗强杀
  - REPORT: 正常完成输出到 ./autonomous_reports/ | 异常写入 stderr + 飞书通知

熔断器和看门狗通过 `tools/circuit_breaker.py` 和 `tools/watchdog.py` 接入。

⚠️ **路径警告**：autonomous_reports 在 temp/ 下，用`./autonomous_reports/`访问，**不是**`../memory/autonomous_reports/`或`../autonomous_reports/`！TODO在cwd下。
报告存于 `./autonomous_reports/`，文件名 `RXX_简短描述.md`（XX从 history.txt 推断自增）。

授权你进行自主行动，只要不对环境造成副作用都可进行。

## 启动（第一步）
- update_working_checkpoint: `自主行动｜收尾时重读SOP | from autonomous_operation_sop.helper import *; set_todo()/complete_task(tasktitle, historyline, report_path)`
- **检查熔断器**：读上次执行日志，若上次跳闸则拒绝执行，等人工审查

第二步：
```python
from autonomous_operation_sop.helper import *
print(get_history(40))  # 了解历史避免重复
print(get_todo())       # 查看待办
```

## 任务选择
- 有未完成条目 → 取**一条**，直接进入执行，其他条目下次执行
- 无 TODO → 读 `autonomous_operation_sop/task_planning.md` 规划，下次执行
- 不连续两次选相同子任务
- 价值公式：**「AI训练数据无法覆盖」×「对未来协作有持久收益」**

## 执行（Closed Loop：必须通过验证器才算完成）
- 选定任务后 update_working_checkpoint，将选中的TODO条目和执行注意事项 append 到 checkpoint 中
- 调用code_run准备结尾回调, script为handler._done_hooks.append("重读自主任务sop，检查你刚刚的收尾工作是否正确，不正确则改正")，inline_eval=True （秘密参数）
- ≤30回合，小步快跑，边探测边实验
- 用临时脚本验证假设；禁只读即下结论，完整验证再写报告
- 即使失败也记录实验过程和结果，失败报告同样有价值
- 用户不在线，遇到需要决策的问题写入报告待审，不要卡住

**Closed Loop 硬约束（不可绕过）**：
- ❌ 禁止模型自判断 done → 必须通过验证器（测试/Lint/Review）才标记完成
- 失败自动回灌日志 → 最多重试3次 → 仍失败则写入报告「未完成+阻断原因」
- 累计3次连续任务失败 → 整体熔断，等待人工审查

**收尾（4件事缺一不可）**：
0. 重读本sop
1. 在cwd写报告（文件名任意），若有记忆更新建议，附在报告末尾
2. `from/import helper; complete_task(tasktitle, historyline, report_path)` → 自动编号+移报告到 autonomous_reports/+prepend history（historyline 格式：`类型 | 主题 | 结论`，严格单行）
3. `set_todo()` 获取TODO路径 → 将已完成条目标记为 `[x]`（注意前缀）
4. 结束，剩余TODO留到下次再做

### REPORT 上报
| 场景 | 通道 |
|------|------|
| 正常完成 | ./autonomous_reports/RXX_xxx.md |
| 异常中断 | stderr + 飞书通知（如有配置） |
| 熔断器跳闸 | stderr + 写入报告 + 拒绝下次启动直到人工审查 |
| 需要人工决策 | 写入报告「待审」条目 |

## 权限边界
- 无需批准：只读探测、cwd内写操作/脚本实验
- 需写入报告待审：修改 global_mem / memory下SOP、安装软件、外部API调用、删除非临时文件
- 绝对禁止：读取密钥、修改核心代码库、不可逆危险操作

## 评估检查（每个关键步骤完成后必做）

### 即时代证伪
每完成一个关键动作，回答3个问题：
1. **产出物存在吗？** 文件/数据/报告 → 已确认路径+大小
2. **产出物正确吗？** 抽样验证（read前几行、grep关键字段）
3. **下一步能接上吗？** 输出格式是否与下一步输入匹配

### 常见失败模式库（持续积累）

| 模式 | 症状 | 正确做法 |
|------|------|---------|
| 假完成 | 工具说success但未验证产出物 | 即时代证伪第1步 |
| 过度Agent | 非GA问题修了别人代码 | 查边界表，对方Agent的任务还回去 |
| 格式崩塌 | 飞书/文件输出格式错误 | 写入前先sample read模板确认格式 |
| 文件丢失 | write后没验证 | 写完后立刻read前N行确认 |
| 飞书表格列错位 | markdown表格</th><td>对齐错乱、列溢出 | 写入飞书docx前先本地渲染；对齐用空格补齐而非tab |
| 文件丢失 | write后没验证 | 写完后立刻read前N行确认 |
| 上下文丢失 | 跨会话不知道上次做了什么 | Progress File + 起始必读 |
| 数据源错 | 用错字段/表名/路径 | 确认字段列表再查询 |

### 失败后的操作
- 同一方法失败**2次**→换方案，不继续打补丁
- 换方案也失败→上报用户，不自作主张
- 把失败模式追加到上面的库（更新本SOP）

## 失败模式反馈循环

核心原则：同样的错误不犯第三次。

### 循环机制
1. **记录**：每次失败 → 追加到 ./trace/{date}.log，并更新SOP顶部失败模式库
2. **识别**：同类错误出现第2次 → 自动升级（从trace识别模式）
3. **修正**：若失败描述包含"因为XXXYYYZZZ固定模式"→ 修正SOP（patch对应节）
4. **验证**：修正后先验证SOP patch有效 → 下次不再犯
5. **守门**：若同一位置被patch过3次仍失败（说明patch逻辑有误） → 上报用户

### 触发条件
- 工具调用失败且不是参数错误 → 记录+分析模式
- 用户指出"这个坑下次别踩了" → 立即升级SOP对应行（见第17行历史踩坑）
- 跨会话同一问题再次出现 → 按"守门"上报

---

## 等待用户审查
- 用户归来后审查报告，决定批准、修改或拒绝方案