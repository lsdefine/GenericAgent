# Plan Mode SOP

**触发**：3步以上有依赖/多文件协同/条件分支/需并行 | **禁用**：1-2步简单任务直接做
任务开始前必须先创建工作目录 `./plan_XXX/`（XXX=任务英文短名）
单独使用一个code_run({'inline_eval':True, 'script':'handler.enter_plan_mode("./plan_XXX/plan.md")'})进入plan模式

---

## 一、探索态（规划前置，必须执行）

⛔ **硬性规则（先读再做）**：

- **主agent禁止直接执行环境探测**（必须委托subagent，无例外）
- 主agent只做：创建目录、匹配SOP、启动subagent、读取结论
- subagent只读探测，禁止修改任何文件、执行有副作用的操作
- **探索subagent启动失败时：排查原因→重试，最多2次。禁止主agent回退为自己探测**

**目标**：在写任何计划之前，搞清3件事：
① 环境现状（有什么、缺什么） ② 可用SOP ③ 关键不确定点

**为什么必须用subagent**：主agent上下文是最稀缺资源，探测长输出会挤占规划执行空间。

### 步骤1：创建目录（必做） + SOP匹配 + 设置plan标志（主agent直接做）

1. 创建工作目录 `mkdir plan_XXX/`
2. 从上下文中的 L1 Insight 索引匹配可用领域SOP
3. 更新checkpoint：`[任务] XXX | [需求] 一句话 | [约束] 关键限制 | [匹配SOP] ... | [进度] 探索态`

### 步骤2：启动探索subagent（监察模式）

按 subagent.md 启动探索subagent，**加 `--verbose`** 开启监察模式，input要点：

- **任务**：探测环境信息，写入 `plan_XXX/exploration_findings.md`
- **探测项**（按任务类型选做，不是全做）：
  - 代码类 → 关键文件结构、依赖、入口点
  - 浏览器类 → 目标页面当前状态、可交互元素
  - 自动化类 → 环境检查(which/pip/路径/权限)
  - 数据类 → 抽样数据(首5行+尾5行+总量)
- **输出格式**：`## 环境现状` / `## 关键发现` / `## 风险/不确定点`
- **约束**：只读探测，禁止修改文件，≤10次工具调用
- **复杂度评估**：探测时注意记录数据规模（文件数、行数、页面数），写入findings供规划时判断委托

### 步骤3：监察等待 + 读取结论

主agent主动观察output.txt进度（`--verbose`输出含原始工具结果），而非无脑sleep轮询：

1. **观察**：读output.txt，审查subagent的探测方向和原始数据
2. **纠偏**（按需）：
   - 方向偏了 → 写 `_intervene` 追加指令纠正
   - 缺少关键上下文 → 写 `_keyinfo` 注入信息
   - 已获取足够信息 → 写 `_stop` 提前终止，节省轮次
3. **收取**：等待 `[ROUND END]`，读取 `exploration_findings.md`

**产出**：`exploration_findings.md`（结构化发现报告），主agent基于此进入规划态，写入plan.md头部的「探索发现」段。主agent在监察过程中获得的一手认知也可直接用于规划。

---

## 二、规划态（含审查门）

### 步骤4：读领域SOP → 写plan.md

先读探索态匹配到的SOP，然后写plan骨架。允许"⚠待确认"，禁止以"没调研清楚"推迟。

**[D] 委托标注规则**：写每个步骤时，结合探索发现评估操作量，符合以下任一条件则标 `[D]`：

- 需要读取大量代码/文件（预估 >3个文件或 >100行）
- 需要浏览网页并提取信息
- 需要执行 3 次以上重复性操作
- 需要运行测试/构建并分析输出

不标 `[D]` 的情况：读/更新 plan.md、单文件小幅修改、ask_user、简单一次性命令

**plan.md格式**：

```markdown
<!-- EXECUTION PROTOCOL (每轮必读，这是你的执行指南)
1. file_read(plan.md)，找到第一个 [ ] 项
2. 该步标注了SOP → file_read 该SOP的🔑速查段
3. 执行该步骤 + Mini验证产出
4. file_patch 标记 [ ] → [✓]+简要结果，然后回到步骤1继续下一个[ ]
5. 所有步骤（包括验证步骤）标记完成后 → 终止检查：file_read(plan.md)确认0个[ ]残留
⚠ 禁止凭记忆执行 | 禁止跳过验证步骤 | 禁止未经终止检查就结束 | 禁止停下来输出纯文字汇报
💡 搬砖活（读大量代码/文件/网页/重复操作）优先委托subagent，保持主agent上下文干净
-->
# 任务标题
需求：一句话 | 约束：关键限制

## 探索发现
- 发现1：XXX（来源：file_read/web_scan/code_run）
- 发现2：YYY
- 不确定点：ZZZ

## 执行计划
1. [ ] 步骤1简述
   SOP: xxx_sop.md
2. [D] 步骤2简述（委托subagent执行）
   SOP: yyy_sop.md
   依赖：1
3. [P] 步骤3简述（并行，读subagent.md执行Map模式）
   SOP: yyy_sop.md
4. [?] 步骤4（条件分支）
   SOP: (无) ← 高风险
   条件：X成功→4.1，否则→4.2

---

## 验证检查点
N+1. [ ] **[VERIFY] 启动独立验证subagent**
     SOP: verify_sop.md plan_sop.md
     操作：读plan_sop.md第四章内容 → 准备verify_context.json → 启动验证subagent → 读取VERDICT → 按结果处理
     ⚠ 不可跳过，不可在未启动subagent的情况下标记[✓]

---
```

### 步骤5：自检清单（主agent逐项检查）

- □ 探索发现是否都反映在plan中？（没遗漏关键约束）
- □ 每步的SOP标注是否合理？（SOP真的能解决该步？）
- □ 步骤间依赖是否正确？（有没有隐含依赖没写出来）
- □ 高风险步骤（SOP:无/不可逆）有没有清晰的执行思路？
- □ 步骤粒度是否合适？（禁止"处理所有文件"，必须展开具体条目）
- □ **复杂/繁琐步骤是否标注了[D]？**（读大量代码/网页/重复操作必须委托subagent）
- □ **是否包含"验证检查点"section，且有[VERIFY]步骤？（必须有，这是强制步骤）**

### 步骤6：用户确认

ask_user 确认plan后才能转入执行态。**⛔ 用户未确认不得执行。**

### 步骤7：转入执行态

更新checkpoint：`[执行] plan.md | 当前：步骤1 | ⚡有[P]标记必须读subagent.md执行Map模式`

---

## 三、执行态循环

> **核心原则：连续执行，不停顿汇报。** 做完一步立即 file_read(plan.md) 找下一个 `[ ]`，直到全部完成。

### 每轮流程

1. **读plan** — `file_read(plan.md)` 定位第一个 `[ ]` 项
2. **读SOP** — 该步标注了SOP → 先 file_read 该SOP
3. **检查标记** — `[D]`标记 → 必须委托subagent执行，主agent只收结果摘要；`[P]`标记 → 读 subagent_sop.md 执行Map模式；`[?]`条件 → 评估条件选分支，未选标[SKIP]
4. **执行** — 无特殊标记的步骤由主agent自己执行
5. **Mini验证** — 快速确认产出存在且合理（file_read确认非空、检查exit code等）
6. **标记完成** — `file_patch` 标记 `[ ]` → `[✓ 简要结果]`（进度写入plan.md）
7. **继续** — 立即回到步骤1，file_read(plan.md) 执行下一个 `[ ]`

### 终止检查（最后一步标记后，不可跳过）

file_read(plan.md) 全文扫描，确认所有步骤（含[VERIFY]）均为 `[✓]`/`[✗]`，0个 `[ ]` 残留。
输出：`🏁 终止检查：[总步数]步全部完成，0个[ ]残留 → 任务结束`
若发现遗漏 → 继续执行，禁止声称完成。

### ⚠ 执行态禁令

- **禁止凭记忆执行**：每次做新步骤前必须 `file_read(plan.md)`，不可"我记得下一步是..."
- **禁止跳过验证步骤**：[VERIFY]步骤是强制的，不可以"任务都做完了"为由跳过
- **禁止未经终止检查就结束**：最后一步标记后必须 file_read 全文扫描确认0个[ ]残留，输出🏁终止确认行
- **禁止停下来输出纯文字汇报**：做完一步后必须立即 file_read(plan.md) 继续，不要输出进度总结

### 💡 动态委托原则

即使步骤未标 `[D]`，执行中发现以下情况时，主动委托 subagent 处理：

- 需要读取大量代码/文件才能理解上下文（>3个文件或预估 >100行）
- 需要反复试错调试
- 需要浏览网页提取信息

做法：起 subagent 完成具体操作，要求返回精简摘要，主 agent 基于摘要继续决策。保持主 agent 上下文干净是第一优先级。

---

## 四、验证态（subagent独立验证）

> 全部步骤[✓]后进入。**强制**启动独立subagent做对抗性验证，避免上下文污染。

### 触发条件

- 所有执行步骤标记为 `[✓]`
- **所有plan模式任务必须经subagent验证**（主agent有确认偏误，易被表面成功迷惑）

### 步骤8：准备验证上下文

在 `./plan_XXX/` 下创建 `verify_context.json`，包含：

- task_description：原始任务描述（用户原话）
- plan_file：plan.md绝对路径
- task_type：code|data|browser|file|system
- deliverables：交付物列表（type/path/expected）
- required_checks：必做检查列表（check/tool）

**传什么**：任务描述、plan路径、交付物清单、必做检查。**不传**：执行过程、调试记录。

### 步骤9：启动验证subagent

按 subagent.md 标准流程启动验证subagent，input要点：

- **角色**：你是独立验证者，工作是对抗性验证（证明交付物不能用）
- **第一步强制**：file_read verify_sop.md 完整阅读验证SOP
- **按 verify_sop.md 第3节**选择对应task_type的验证策略执行
- **每个检查必须有工具调用证据**（实际执行，不是叙述）
- **任务描述**：（填入原始任务描述）
- **交付物清单**：（填入deliverables列表）
- **输出**：在 result.md 中按 verify_sop.md 第6节格式输出，最后一行 `VERDICT: PASS / FAIL / PARTIAL`
- **约束**：3轮内完成，每轮至少1个实际工具调用

同时传入 verify_context.json 的路径，让subagent自行读取详细上下文。

### 步骤10：收集验证结果

轮询 output.txt 等待 `[ROUND END]`，然后读取 result.md：

1. **找VERDICT行**：读取result.md最后几行，提取 `VERDICT: PASS/FAIL/PARTIAL`
2. **检查有效性**：如果所有PASS项都没有工具调用输出（只有叙述），视为验证无效，按FAIL处理
3. **按结果处理**：
   - **PASS** → 进入任务完成收尾
   - **FAIL** → 进入修复循环
   - **PARTIAL** → 主agent判断可接受则完成，否则修复
   - **无VERDICT行** → 从output.txt提取关键信息，主agent自行判断PASS/FAIL

**任务完成收尾**（验证PASS后执行）：

1. 标记plan.md中 `[VERIFY]` 步骤为 `[✓]`
2. 更新checkpoint：`[完成] XXX任务 | [产出] ... | [经验] ...`
3. 向用户确认任务完成

**重要**：只有在验证PASS后，才能标记[VERIFY]为[✓]并声称任务完成。如果验证FAIL，需要进入修复循环。

**Fallback**：若subagent未产出result.md（turn耗尽），从output.txt提取VERDICT关键信息。

### 修复循环（FAIL后）

FAIL → 提取具体失败项 → 回执行态修复（不重新规划） → 修复完成 → 再次启动验证subagent → 最多2轮FAIL-重试，超过 ask_user 介入

修复时：

1. 将FAIL项作为新步骤追加到plan.md（标记为 `[FIX]`）
2. 只修复失败项，不重做已PASS的部分
3. 修复完成后重新准备verify_context.json（只含失败项）

### 特殊场景处理

浏览器/键鼠/定时任务等场景：主agent执行操作并导出证据（截图/录屏/日志）→ subagent验证证据文件。**禁止主agent自行判断PASS/FAIL**。

---

## 五、失败处理

1. **记录**：checkpoint中 `step_X: [FAILED] 原因 (retry: N/3)`
2. **重试**：网络超时→自动重试3次(2s/4s/8s) | 配置错误→询问用户 | 其他→标[✗]跳过
3. **subagent失败**：查stderr.log→明确错误主agent修正重启 | 未知错误重试1次 | 最多重启2次
4. **依赖传播**：步骤失败后，后续依赖项标[SKIP]
5. **plan有误**：回退到规划态修正plan.md，重新过审查门

## 强制约束

- 每项必须有独立完成判据
- 禁止"处理所有文件"，必须展开具体条目
- 一次只做一项；计划有误回规划态修正
- 不可逆操作前多验证一步
