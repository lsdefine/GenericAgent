# Review Mode SOP

> In-session adversarial code reviewer。用 `/review` 触发,主 agent 在当前对话内
> 拉起评审,报告直接 echo 到对话,**不开 subagent / 不落盘 / 不打 sentinel**。

---

## 一、何时使用

用户输入 `/review` 命令,或自然语言要求"code review"时启用。
典型用例:作者刚写完一段代码 → `/review` 对自己的改动做对抗性 review。

---

## 二、快速启动

| 命令 | 行为 |
|---|---|
| `/review` | 默认审本次 uncommitted 改动(主 agent 跑 `git diff --stat HEAD` + `git diff HEAD`) |
| `/review <自然语言请求>` | 按描述的范围去审(可指定文件 / 目录 / 任务) |
| `/review help` | 显示用法 |

**非 git 仓库**:主 agent 提示用户在下一句 `/review` 塞入具体路径或范围,本轮结束。

---

## 三、入口文件

```
任意前端 (TUI / Streamlit / wechat / desktop)
   └─ frontends/review_cmd.py     ← 命令分发,剥 "/review" 前缀,注入 user_request
       └─ memory/review_sop/review_inline_prompt.txt   ← 完整 in-session 协议
           └─ memory/code_review_principles.md         ← 15 条好代码原则
```

- `review_cmd.py:install()` —— monkey-patch `GenericAgent._handle_slash_cmd`,统一接管 `/review`
- `review_cmd.py:_render_prompt()` —— 加载 prompt 模板,注入 `{user_request}` + `{ga_root}`

---

## 四、三条铁律(reviewer 顶部硬约束,不可违反)

1. **Review-only 只读评审** —— 评审与报告而已。**禁止**修改源文件、调
   file_write / file_patch / code_run 改业务代码、在产出里写"我接下来去修一下"
   或暗示要动手。
2. **Challenge the approach, 不仅找 bug** —— 先问"这条路本身对不对?"再问
   "实现有没有 bug?":挖隐含假设、评估真实环境故障模式(Windows 路径 / 代理失活 /
   并发写 / UTF-8 边界 / token 预算耗尽)。
3. **报告输出完即结束** —— 不复述用户目标、不做 meta 评论、不承诺 follow-up;
   报告 markdown 直接 echo 到对话,**不落盘 review.md、不打 `[ROUND END]`**。

---

## 五、工作流(5 步,顺序走)

### 步骤 1:必读底料

`file_read("memory/code_review_principles.md")` —— 15 条好代码原则,**每条 finding 必须
能映射到其中一条**。

### 步骤 2:锁定审阅范围

| 用户输入 | 范围 |
|---|---|
| 点名了文件 / 目录 | 审那些 |
| 描述了任务范围 | `code_run` 跑 `git status -s` + `git diff --stat HEAD` + `git diff HEAD` |
| 空 / 模糊 | 默认审本次 uncommitted 改动 |
| 非 git 仓库 | 提示用户塞路径,本轮结束 |

**先把范围列出来发给用户确认**,再开始 `file_read`。

### 步骤 3:逐文件 file_read

超过 800 行分段读。优先看 diff 涉及的行,再看上下文与接口调用方。

### 步骤 4:回答 Q1-Q4 对抗性 framing

- **Q1: Is this the right approach?** — 有没有更简单 / 更标准 / 更安全的实现路径?
- **Q2: What hidden dependencies could fail?** — OS / shell / 网络 / 并发 / 第三方 API 任一失效?
- **Q3: What edge / hostile input breaks it?** — 空值、UTF-8、Windows 路径、超长输入、过期 token。
- **Q4: Is the failure mode observable & recoverable?** — 仅看日志能不能定位?能不能不动手就恢复?

### 步骤 5:列 P0~P3 findings

遵守 §七 防误报八规则 + §八 措辞八规范。提交前过自检清单(§九)。

---

## 六、Severity / Verdict 速查

| Level | 定义 | 例子 |
|---|---|---|
| **P0** | 阻塞:破坏正确性 / 丢数据 / 安全漏洞 / 不可逆故障 | 路径穿越、SQL 注入、密钥落日志、并发竞态破坏数据 |
| **P1** | 高危:契约破坏 / 用户可见错误,但不会立即崩 | 错误只 print 不抛、超时未设、API schema 不一致 |
| **P2** | 维护性:可读性 / 命名 / 测试空缺 | 函数 > 80 行、duplicate logic、注释与代码不符 |
| **P3** | 风格 / 微优化 / 可选改进 | 命名小调整、常量提取、import 顺序 |

**Verdict 决议**:任一 P0 → `FAIL`;无 P0 但 ≥ 1 P1 → `CONDITIONAL`;仅 P2/P3 或 0 finding → `PASS`。

---

## 七、防误报八规则(成本低到高,任一答 No → 删 finding)

1. **Discrete & actionable** — 有具体可写的修复?
2. **Introduced or exposed by this change** — 本次改动引入或放大?
3. **Not an intentional design choice** — 不是作者刻意取舍?
4. **Provably affected, not speculated** — 跨文件影响能指出调用栈?
5. **Evidence-anchored** — 行号 / 代码片段 / 复现至少一项?
6. **No unstated assumptions** — 不依赖未明说的"应该这样"?
7. **Author would likely fix if made aware** — 作者会同意修?
8. **Impact meaningful + proportionate rigor** — 影响足够 + 严谨度匹配代码库?

> 每条规则的展开详见 `memory/review_sop/review_inline_prompt.txt` §5。

---

## 八、措辞八规范

1. **Why-first** — 第一句给原因。
2. **严重度准确** — 不要把 P2 写得像 P0。
3. **简洁** — `evidence` / `impact` / `fix` 各 ≤ 1 段。
4. **少贴大段代码** — `evidence` 代码 ≤ 5 行,超过用 `file:line-line` 引用。
5. **触发条件显式** — `impact` 首句必带场景 / 输入 / 环境。
6. **不卑不亢** — 直陈事实,无情绪 / 无开场白。
7. **即读即懂** — 核心结论放第一句。
8. **零奉承** — 不写 "Great work, but...", "Thanks for the changes, however..."。

> 展开详见 `memory/review_sop/review_inline_prompt.txt` §6。

---

## 九、输出协议(整段 echo,不落盘)

```
## Scope
<一行一个文件,绝对路径或仓库相对路径>

## Verdict
PASS / CONDITIONAL / FAIL

## Summary
3-6 行散文:整体印象 + 最重要的 1-2 个风险。

## Design Challenge (Q1-Q4)
- **Q1 是不是对的方法**: <证据>
- **Q2 隐藏依赖**: <证据>
- **Q3 边缘 / 敌意输入**: <证据>
- **Q4 故障可观测**: <证据>

## Findings (P0 → P3 顺序)
- **[P0, conf=0.9] file:line-line** 标题(动词开头,≤ 80 字,第一句给原因)
  - **Evidence**: 代码片段 ≤ 5 行 或 file:N-M 引用
  - **Impact**: 触发场景 + 后果(第一句必带场景)
  - **Fix**: 可直接照做的修复思路,≤ 1 段
  - **Principle**: 对应 code_review_principles 第 N 条

## Cross-file notes
跨文件耦合 / 命名一致性 / 状态机 / 并发问题。无则 `(none)`。

## Regression tests
3-5 条具体测试点(输入 / 预期 / 边界)。
```

---

## 十、扩展点

- **自定义评审条目**:编辑 `memory/code_review_principles.md`,reviewer 启动时整段注入
- **触发更换**:要把 `/review` 改成别的命令,只动 `frontends/review_cmd.py` 的 `install()` 一处
