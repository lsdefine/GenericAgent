---
version: 1.0
last_updated: "2026-05-30"
---

# GitHub Contribution SOP
**触发**：需要给开源项目提 PR（修 bug / 加功能 / 改文档）| **禁用**：仅读代码、不需要提交变更时
**核心原则**：一个 PR 做一件事，测试通过才推，尊重项目规范

## 前置准备（每个新项目首次执行）
1. **读项目规范**（必须，不可跳过）
   ```
   file_read('CONTRIBUTING.md')  # 贡献指南
   file_read('.github/PULL_REQUEST_TEMPLATE.md')  # PR 模板
   file_read('.github/ISSUE_TEMPLATE/')  # Issue 模板
   ```
   没有就读 README 的 Contributing 部分。如果都没有，按本 SOP 默认流程。

2. **了解项目结构和测试方式**
   ```
   # 找测试命令
   file_read('package.json')  # Node: scripts.test
   file_read('Makefile')      # 或 Makefile
   file_read('pyproject.toml') # Python: [tool.pytest] 等
   ```
   记下测试命令备用。跑不了测试的 PR = 未验证的 PR。

3. **Fork + Clone**
   ```
   code_run('bash', 'gh repo fork OWNER/REPO --clone && cd REPO && git remote -v')
   ```

## 工作流程（每个 PR）

### Step 1: 确认目标
- 读相关 Issue（如果有）
- 一句话写清楚：改什么、为什么改
- 检查：是否有人已在做？（看 Issue assignee、近期 PR）

### Step 2: 创建分支
```
code_run('bash', 'git checkout -b fix/issue-描述 && git status')
```
分支命名：`fix/xxx`（修 bug）、`feat/xxx`（新功能）、`docs/xxx`（文档）

### Step 3: 实现变更
- **最小化改动**：只改需要改的，不顺手重构无关代码
- **遵循项目风格**：缩进、命名、注释风格跟现有代码保持一致
- **每改一个逻辑点就提交一次**：
  ```
  code_run('bash', 'git add -A && git commit -m "fix: 简洁描述"')
  ```
- Commit message 格式：遵循项目规范（Conventional Commits / 项目自定义）
  - 没有规范就用：`type: 简短描述`
  - type: fix / feat / docs / refactor / test / chore

### Step 4: 测试（不可跳过）
```
code_run('bash', '项目测试命令')  # npm test / pytest / go test ./...
```
**检查项**：
- [ ] 所有现有测试通过？
- [ ] 新功能有对应测试？（如果项目有测试习惯）
- [ ] lint/type check 通过？（如果项目有）

**⛔ 测试不过不推代码。修到过为止。**

### Step 5: 推送 + 提 PR
```
code_run('bash', 'git push origin HEAD')
```
PR 内容：
- **标题**：`type: 简洁描述` 或按项目模板
- **正文**必须包含：
  - 改了什么（What）
  - 为什么改（Why）— 关联 Issue 用 `Fixes #123`
  - 怎么测的（Testing）
- **不要写**：过度解释、无关背景、自夸

### Step 6: CI 检查
PR 提交后等 CI：
- ✅ 全过 → 等 review
- ❌ 有失败 → 看日志，修自己的问题
  - CI 失败是 upstream 问题（跟你的改动无关）→ 在 PR 里说明
  ```
  code_run('bash', 'gh run view --log-failed')
  ```

### Step 7: 回应 Review
- **reviewer 说改就改**，不要争论风格偏好
- **不同意的技术决定**：礼貌说明理由，但最终尊重 maintainer
- **改完后**：追加 commit + 测试 + push，不要 force push（除非 maintainer 要求 squash）
- **reviewer 要求加测试** → 加，这不是可选项

## 常见错误（避坑）

| 错误 | 正确做法 |
|------|----------|
| 一个 PR 改多件事 | 拆成多个 PR，每个独立 |
| 提了 PR 不跟进 | 每天检查 review 状态 |
| 测试没跑就推 | Step 4 是硬门槛 |
| 改了代码风格混乱 | 跟现有代码一致 |
| commit message 写 "update" | 写具体改了什么 |
| force push 覆盖 review 历史 | 追加 commit |
| PR 描述空白 | 写 What/Why/Testing |

## 跟进状态机

```
PR 提交 → 等 CI
  CI ✅ → 等 Review
    Review 通过 → 等 Merge ✅
    Review 要改 → 改 + 测试 → 重回等 CI
  CI ❌ → 修 → 重回等 CI
```

每轮跟进用：
```
code_run('bash', 'gh pr status')
code_run('bash', 'gh pr checks PR_NUMBER')
code_run('bash', 'gh pr view PR_NUMBER --comments')
```
