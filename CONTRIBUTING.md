# Contributing to GenericAgent

> 感谢您对 GenericAgent 的关注！欢迎提交 Issue 和 Pull Request。
> Thank you for your interest in GenericAgent! Issues and Pull Requests are welcome.

---

## Table of Contents / 目录

- [Code Style / 代码风格](#code-style--代码风格)
- [Branch Strategy / 分支策略](#branch-strategy--分支策略)
- [Testing Requirements / 测试要求](#testing-requirements--测试要求)
- [Commit Message Format / 提交信息格式](#commit-message-format--提交信息格式)
- [PR Description Format / PR 描述格式](#pr-description-format--pr-描述格式)
- [Issue Guidelines / Issue 指南](#issue-guidelines--issue-指南)

---

## Code Style / 代码风格

### Python / Python 代码

- Use **Python 3.11+** (Python 3.14 is NOT supported due to dependency compatibility)
- Use **4 spaces** for indentation (no tabs)
- Keep lines under **120 characters** when reasonable
- Add docstrings for functions and classes using the project's format:

```python
def code_run(code, code_type="python", timeout=60, cwd=None, code_cwd=None, stop_signal=[]):
    """代码执行器
    
    python: 运行复杂的 .py 脚本（文件模式）
    powershell/bash: 运行单行指令（命令模式）
    优先使用python，仅在必要系统操作时使用powershell。
    """
    # implementation
```

### Naming Conventions / 命名规范

- Functions: `snake_case` (e.g., `code_run`, `fetch_web_content`)
- Classes: `PascalCase` (e.g., `BaseHandler`, `ReflectMode`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`, `DEFAULT_TIMEOUT`)
- Private methods: prefix with `_` (e.g., `_internal_method`)

### File Organization / 文件组织

- Main logic in `.py` files (e.g., `ga.py`, `llmcore.py`)
- UI components in `frontends/` directory
- Skills/memory in `memory/` directory
- Assets in `assets/` directory
- Tests in `tests/` directory

---

## Branch Strategy / 分支策略

### Branch Naming / 分支命名

| Type / 类型 | Pattern / 模式 | Example / 示例 |
|------------|---------------|---------------|
| Feature | `feat/description` | `feat/add-voice-cloning` |
| Bug Fix | `fix/description` | `fix/desktop-pet-port` |
| Documentation | `docs/description` | `docs/add-api-examples` |
| Refactor | `refactor/description` | `refactor/plan-mode` |
| Test | `test/description` | `test/add-minimax-coverage` |

### Workflow / 工作流程

1. Create a new branch from `main`: `git checkout -b feat/your-feature`
2. Make your changes
3. Run tests locally
4. Push and create PR against `main`
5. Wait for review and address feedback

---

## Testing Requirements / 测试要求

### Test Structure / 测试结构

```bash
tests/
├── __init__.py
├── conftest.py           # shared fixtures
├── test_module.py        # unit tests
└── test_module_integration.py  # integration tests (with network calls)
```

### Running Tests / 运行测试

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_minimax.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

### Test Style / 测试风格

- Use **unittest** framework (see `tests/test_minimax.py` for reference)
- Mock external API calls in unit tests
- Integration tests should be auto-skipped when API keys are not available:

```python
import unittest
import os

class TestMiniMaxIntegration(unittest.TestCase):
    @unittest.skipIf(not os.getenv('MINIMAX_API_KEY'), "Requires MINIMAX_API_KEY")
    def test_live_api(self):
        # integration test
        pass
```

### Validation Before PR / PR 前验证

- [ ] All unit tests pass: `python -m pytest tests/test_*.py -v` (skip integration)
- [ ] Syntax check: `python -m py_compile your_file.py`
- [ ] No new flake8/lint errors (if linting is introduced)

---

## Commit Message Format / 提交信息格式

### Format / 格式

```
type(scope): short description in English

Optional longer description in English or Chinese.
Can be multiple lines.
```

### Type Categories / 类型分类

| Type | Description / 描述 |
|------|-------------------|
| `feat` | New feature / 新功能 |
| `fix` | Bug fix / 修复 bug |
| `docs` | Documentation only / 仅文档 |
| `refactor` | Code refactoring / 代码重构 |
| `test` | Adding or updating tests / 添加或更新测试 |
| `chore` | Build, CI, dependencies / 构建、CI、依赖 |

### Examples / 示例

```
feat(llmcore): add MiniMax streaming support

fix(frontends): resolve desktop pet port conflict on Windows

docs(readme): add installation video link

refactor(agent_loop): simplify state management logic
```

---

## PR Description Format / PR 描述格式

### Required Sections / 必要部分

```markdown
## Summary / 概述
Brief description of what this PR does.

## What / 主要改动
- Change 1
- Change 2

## Why / 为什么
Explain the motivation or problem being solved.

## Testing / 测试
How was this tested?
- [ ] Test 1
- [ ] Test 2

## Notes / 备注
Any additional context or known limitations.
```

### Example / 示例

```markdown
## Summary
Adds MiniMax TTS as a new voice generation backend.

## What
- Added `memory/exa_search.py` for Exa AI search integration
- Added `memory/exa_search_sop.md` with usage documentation
- Added 22 unit tests with mocked API calls

## Why
Users needed semantic web search capability for research tasks.

## Testing
- [x] `python -m pytest tests/test_exa_search.py -v` → 22 passed
- [x] Existing test suite unaffected
- [ ] Live API smoke test (requires EXA_API_KEY)

## Notes
- `exa-py>=2.0.0` is lazily imported, so core install is unaffected
- No changes to `ga.py`, `agent_loop.py`, or the 9-tool atomic set
```

---

## Issue Guidelines / Issue 指南

### Before Creating an Issue / 创建 Issue 前

- [ ] Search existing issues to avoid duplicates
- [ ] Check if the issue is about usage help (consider Discussions instead)
- [ ] Confirm the issue persists on latest version

### Issue Types / Issue 类型

| Type | When to Use / 何时使用 |
|------|----------------------|
| **Bug Report** | Something doesn't work as expected / 功能不按预期工作 |
| **Feature Request** | Request a new capability / 请求新功能 |
| **Question** | Usage help or clarification / 使用帮助或澄清 |
| **Enhancement** | Improve existing functionality / 改进现有功能 |

### Bug Report Template / Bug 报告模板

```markdown
## 问题描述 / Description
Describe the bug clearly.

## 环境 / Environment
- OS: (e.g., Windows 11, macOS 14)
- Python version: (e.g., 3.12)
- Project version/commit:

## 复现步骤 / Steps to Reproduce
1. Go to '...'
2. Run '...'
3. See error

## 预期行为 / Expected Behavior
What should happen.

## 实际行为 / Actual Behavior
What actually happens.

## 截图 / Screenshots
If applicable.
```

### Feature Request Template / 功能请求模板

```markdown
## 功能描述 / Feature Description
Describe the feature you want.

## 使用场景 / Use Case
Who would use this and why?

## 建议的实现 / Proposed Implementation
If you have ideas on how to implement this.

## 参考 / References
Any relevant links, similar features in other projects.
```

---

## Questions? / 有问题？

- Check [README.md](README.md) and [GETTING_STARTED.md](GETTING_STARTED.md) first
- Open a [Discussion](https://github.com/lsdefine/GenericAgent/discussions) for questions
- Search existing issues before creating new ones

---

## License / 许可证

By contributing, you agree that your contributions will be licensed under the same MIT License as this project.
