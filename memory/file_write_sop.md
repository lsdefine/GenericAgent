# file_write SOP — Tool Call & Robust Failure Handling (Revised)

## Purpose
彻底减少使用 `file_write` 工具时出现“未在回复中找到<file_content>代码块内容”错误的概率，并在不可避免时提供可靠的绕路与可审计日志。

## Key points (summary)
- file_write 工具读取的是“助手回复正文”中的 <file_content> 区块，非工具参数；因此必须确保助手回复中有完整、未被转义的区块。
- 常见根因：区块缺失、回复被处理或截断、并发/上下文切换、工具接口设计限制、路径或权限被拒绝而被泛化为该错误。

## Recommended flow (short-term)
1. 优先使用本地直接写入（code_run / scripts/file_write_helper.write_direct）以绕开依赖回复正文的工具。
2. 必须使用 file_write 时：
   - 在回复中先包含完整的 <file_content> 区块（工具严格匹配），随后再发起 tool call。
   - 在回复中同时包含一段 human-readable 操作摘要与校验步骤（路径/encoding/size/hash）。
3. 每次写入均在 memory/file_write_journal.log 记录操作元数据（ts、path、length、method、ok/hash）。
4. 限次重试：同一路径失败时最多重试 2 次，之后 ask_user 干预。

## Medium-term wrapper
- 在 memory/utils.py 增加 safe_file_write_wrapper(path, content, use_tool=False) 函数：
  - 若 use_tool=False：直接写入并返回验证结果。
  - 若 use_tool=True：返回构造好的 <file_content> 区块（供回复使用），并在本地记录请求ID与预期 hash，等待工具返回后核对。

## Tests
- 提供 temp/test_file_write_tool.py：覆盖 direct write、build-block、journal 以及 failure/retry 行为。

## Verify Claims
- 成功写入后必须执行 file_read 或 code_run 验证，并将验证结果追加到 journal 中。

## Change log
- 2026-05-04 Revised: 增加 helper、wrapper、journal；明确短/中/长期策略。
