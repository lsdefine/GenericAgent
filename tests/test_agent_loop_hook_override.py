#!/usr/bin/env python3
"""AST-source-extraction harness for agent_runner_loop hook-override fix (PR #714).

Exercises the literal upstream source via ast.unparse on the prologue
statements — no exec of the full function body, no plugins/hooks import.

Fix scope: when _hook('agent_before', locals()) returns a dict, apply
  system_prompt -> messages[0]['content']
  initial_user_content -> messages[1]['content']  (takes precedence over user_input)
  user_input -> messages[1]['content']            (only when initial_user_content is None)

This is the second housekeeping commit (f3a06ee) of PR #714 — adds the
documentation + the precedence note. The first commit (1732eca) was the actual
behavior fix.

Tests:
  1. system_prompt override -> messages[0] patched
  2. legacy None-return -> messages unchanged (backward compat)
  3. non-dict return -> messages unchanged (backward compat)
  4. initial_user_content wins over user_input when both returned
  5. user_input applied when no initial_user_content
  6. parent-commit pin: old code would have dropped the override
"""
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "agent_loop.py"


def _extract_prologue():
    """Return just the messages list + _hook handling prologue (ast.unparsed)."""
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "agent_runner_loop":
            # Take only the statements up to (not including) `while turn < ...`.
            keep = []
            for stmt in node.body:
                if isinstance(stmt, ast.While):
                    break
                keep.append(stmt)
            return ast.unparse(keep)
    raise RuntimeError("agent_runner_loop not found")


def _run_hook_block(hook_returns, system_prompt="ORIGINAL", user_input="USER",
                    initial_user_content=None):
    """Execute the upstream prologue with a controlled _hook, return messages."""
    ns = {"_hook": lambda *a, **k: hook_returns, "__builtins__": __builtins__}
    prologue = _extract_prologue()
    # Wrap in a function so the parameter names resolve.
    func_src = (
        "def _f(client, system_prompt, user_input, handler, tools_schema, "
        "max_turns=40, verbose=True, initial_user_content=None, yield_info=False):\n"
        + "\n".join("    " + l for l in prologue.split("\n"))
        + "\n    return messages\n"
    )
    class _FakeHandler:
        max_turns = 0
    exec(func_src, ns)
    return ns["_f"](None, system_prompt, user_input, _FakeHandler(), None,
                    initial_user_content=initial_user_content)


# ────────────────────────────────────────────────────────────────────────────
# Test 1: system_prompt override
# ────────────────────────────────────────────────────────────────────────────
def test_system_prompt_override():
    msgs = _run_hook_block(
        hook_returns={"system_prompt": "[AUGMENTED] new sys"},
        system_prompt="ORIGINAL prompt",
        user_input="hello",
    )
    assert msgs[0]["content"] == "[AUGMENTED] new sys", f"got: {msgs[0]!r}"
    assert msgs[1]["content"] == "hello", f"user input should be unchanged: {msgs[1]!r}"
    print("✓ test_system_prompt_override")


# ────────────────────────────────────────────────────────────────────────────
# Test 2: legacy None return — backward compat
# ────────────────────────────────────────────────────────────────────────────
def test_none_return_unchanged():
    msgs = _run_hook_block(
        hook_returns=None,
        system_prompt="ORIGINAL prompt",
        user_input="hello",
    )
    assert msgs[0]["content"] == "ORIGINAL prompt"
    assert msgs[1]["content"] == "hello"
    print("✓ test_none_return_unchanged")


# ────────────────────────────────────────────────────────────────────────────
# Test 3: non-dict return (e.g., string) — backward compat
# ────────────────────────────────────────────────────────────────────────────
def test_non_dict_return_unchanged():
    msgs = _run_hook_block(
        hook_returns="some log string from hook",
        system_prompt="ORIGINAL",
        user_input="user text",
    )
    assert msgs[0]["content"] == "ORIGINAL"
    assert msgs[1]["content"] == "user text"
    print("✓ test_non_dict_return_unchanged")


# ────────────────────────────────────────────────────────────────────────────
# Test 4: initial_user_content takes precedence over user_input
# ────────────────────────────────────────────────────────────────────────────
def test_initial_user_content_precedence():
    msgs = _run_hook_block(
        hook_returns={"initial_user_content": "PLUGIN_OVERRIDE", "user_input": "CALLER_VALUE"},
        system_prompt="ORIGINAL",
        user_input="CALLER_DEFAULT",
        initial_user_content="CALLER_DEFAULT",
    )
    assert msgs[1]["content"] == "PLUGIN_OVERRIDE", (
        f"plugin override should win; got: {msgs[1]!r}"
    )
    print("✓ test_initial_user_content_precedence")


# ────────────────────────────────────────────────────────────────────────────
# Test 5: user_input applied when no initial_user_content
# ────────────────────────────────────────────────────────────────────────────
def test_user_input_when_no_initial_user_content():
    msgs = _run_hook_block(
        hook_returns={"user_input": "PLUGIN_USER"},
        system_prompt="ORIGINAL",
        user_input="DEFAULT_USER",
        initial_user_content=None,
    )
    assert msgs[1]["content"] == "PLUGIN_USER"
    print("✓ test_user_input_when_no_initial_user_content")


# ────────────────────────────────────────────────────────────────────────────
# Test 6: parent-commit pin — pre-fix code drops the override
# Reproduce the OLD pre-fix prologue (just call _hook, ignore the return) and
# assert that this loses the override, proving the fix is non-trivial.
# ────────────────────────────────────────────────────────────────────────────
def test_parent_commit_pin():
    old_block = """
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": initial_user_content if initial_user_content is not None else user_input}
]
_hook('agent_before', locals())  # OLD: return value discarded
result = messages
"""
    ns = {
        "_hook": lambda *a, **k: {"system_prompt": "[AUGMENTED]"},
        "system_prompt": "ORIGINAL prompt",
        "user_input": "hello",
        "initial_user_content": None,
        "__builtins__": __builtins__,
    }
    exec(old_block, ns)
    old_messages = ns["result"]
    assert old_messages[0]["content"] == "ORIGINAL prompt", (
        "pre-fix code should silently drop the system_prompt override — this "
        f"proves the fix is non-trivial; got messages[0]: {old_messages[0]!r}"
    )
    print("✓ test_parent_commit_pin (pre-fix drops override)")


if __name__ == "__main__":
    test_system_prompt_override()
    test_none_return_unchanged()
    test_non_dict_return_unchanged()
    test_initial_user_content_precedence()
    test_user_input_when_no_initial_user_content()
    test_parent_commit_pin()
    print("\nAll 6 tests passed.")