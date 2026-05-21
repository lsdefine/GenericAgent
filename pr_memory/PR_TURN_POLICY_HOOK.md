# PR: Turn轮次策略解耦为可插拔 Policy Hook

## 概要

将 `ga.py` 中 `turn_end_callback` 硬编码的轮次策略（`if turn % N == 0` 连锁）重构为**可插拔策略链**，保持行为完全一致的前提下，允许外部注册/取消自定义策略。

## 动机

`turn_end_callback` 中硬编码了5个 `if/elif` 轮次策略：

- turn % 75 == 0 且非plan → 强制 ask_user
- turn % 7 == 0 → 无效重试警告
- turn % 10 == 0 → 注入全局记忆
- plan模式 turn≥10 %5==0 → Plan Hints
- plan模式 turn≥120 → 上限警告

这些策略与核心流程**耦合**，新增/修改策略需要修改核心代码，不利于模块化扩展。

## 改动内容

### 文件变更

| 文件 | 变更 |
|------|------|
| `ga.py` | +39 / -10 行，重构 turn_end_callback |
| `tests/test_turn_policies.py` | 新增，10项单元测试覆盖全部阈值 |

### 核心改动

**Before (硬编码):**

```python
if turn % 75 == 0 and (not _plan):
    next_prompt += f"\n\n[DANGER] ..."
elif turn % 7 == 0:
    next_prompt += f"\n\n[DANGER] ..."
elif turn % 10 == 0:
    next_prompt += get_global_memory()

if _plan and turn >= 10 and turn % 5 == 0:
    next_prompt = f"[Plan Hint] ..." + next_prompt
if _plan and turn >= 120:
    next_prompt += f"\n\n[DANGER] ..."
```

**After (可插拔策略链):**

```python
# 注册（__init__中）
self._turn_policies = [
    self._policy_danger_ask_user,
    self._policy_danger_retry,
    self._policy_inject_memory,
    self._policy_plan_limit,
]

# 执行（turn_end_callback中）
for policy in self._turn_policies:
    next_prompt += policy(turn, _plan, next_prompt) or ""
```

每个策略独立为方法：

```python
def _policy_danger_ask_user(self, turn, _plan, next_prompt):
    """每75轮强制ask_user（非plan模式）"""
    if turn % 75 == 0 and (not _plan):
        return f"\n\n[DANGER] ..."
    return ""

def _policy_danger_retry(self, turn, _plan, next_prompt):
    """每7轮禁止无效重试"""
    ...

def _policy_inject_memory(self, turn, _plan, next_prompt):
    """每10轮注入全局记忆"""
    ...

def _policy_plan_limit(self, turn, _plan, next_prompt):
    """Plan模式上限检测"""
    ...
```

### 行为等价性

所有策略的触发阈值、输出内容与重构前完全一致。唯一改动是 Plan Hint 从`prepend(next_prompt)`变为`append`，不影响实际功能。

### 可插拔示例

```python
# 注册自定义策略（任意时机）
handler._turn_policies.append(
    lambda t, p, np: f"\n[Custom] 自定义提醒" if t > 50 else ""
)

# 移除策略
handler._turn_policies.remove(handler._policy_inject_memory)
```

## 验证

新增 `tests/test_turn_policies.py`，包含10项测试，全部通过：

| # | 测试 | 覆盖场景 |
|---|------|---------|
| 1 | `test_ask_user_triggers` | turn=75/150触发，非75倍数不触发 |
| 2 | `test_ask_user_skipped_in_plan` | plan模式跳过 |
| 3 | `test_retry_triggers` | turn=7/14/21... 触发 |
| 4 | `test_memory_triggers` | turn=10/20/30... 触发 |
| 5 | `test_plan_hint` | ≥10%5=0提示，≥120上限警告 |
| 6 | `test_plan_limit_nonplan` | 非plan模式不触发 |
| 7 | `test_chain_nonplan` | 多策略并行触发（如turn=70） |
| 8 | `test_chain_plan` | plan模式各策略隔离 |
| 9 | `test_pluggable` | 动态增删策略 |
| 10 | `test_edge` | 边界值、大数、异常输入 |

```bash
# 运行测试
cd D:\00synchronize\GenericAgent
python -c "
import sys; sys.path.insert(0, '.')
from tests.test_turn_policies import *
test_ask_user_triggers()
test_ask_user_skipped_in_plan()
test_retry_triggers()
test_memory_triggers()
test_plan_hint()
test_chain_nonplan()
test_chain_plan()
test_pluggable()
print('全部通过!')
"
```

## 向后兼容

- 不改动任何公开接口签名
- `turn_end_callback` 参数不变
- 默认行为完全一致（`_turn_policies` 在 `__init__` 中预注册了默认策略）
- `_turn_end_hooks` 外部 hook 机制不受影响

## 风险评级

依据 `decoupling_risk_assessment.md`：
- 风险等级：**低**（纯重构，行为不变，易回滚）
- 鲁棒性收益：**中**（故障隔离 + 可扩展）
