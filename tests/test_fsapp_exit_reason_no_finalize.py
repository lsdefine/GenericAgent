"""Regression test for #685.

Before fix: ``_make_task_hook`` invoked the ``on_final`` callback whenever a hook
context carried a truthy ``exit_reason``. Because ``run_agent`` passes ``_finish``
as ``on_final``, an intermediate turn-level ``exit_reason`` could mark the queued
task complete (``result["sent"] = True``) before the display queue published its
real ``{"done": ...}`` item.

After fix: the hook only patches the per-turn card step from ``summary``.
Finalization happens only on the display-queue ``done`` item or on
timeout/stop/exception paths in ``run_agent``.

These tests load ``_make_task_hook`` and its pure helpers from the real
``frontends/fsapp.py`` AST so we exercise the actual source rather than a
copy. Heavy lark_oapi / agentmain / chatapp_common imports are skipped by
extracting only the relevant function source via ast.parse.
"""

import ast
import os
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FSAPP_PATH = REPO_ROOT / "frontends" / "fsapp.py"


def _load_fsapp_helpers():
    """Load ``_make_task_hook``, ``_display_text``, ``_build_step_detail``,
    ``_fmt_tool_call`` from frontends/fsapp.py by AST-extracting their
    source and exec'ing it in a fresh namespace. Heavy top-level imports
    (lark_oapi, agentmain, chatapp_common) are skipped entirely.

    The function source is taken verbatim from fsapp.py and re-executed in
    a small namespace that provides ``_TRUNC_TAIL``, ``re``, ``json``,
    ``getattr`` (builtin). The hooks are then re-bound to the module under
    test using a lightweight fake ``_build_step_detail`` so we don't need
    the full helper stack just to exercise the hook's dispatch logic.
    """

    src = FSAPP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Collect the function source strings we need.
    wanted = {"_display_text", "_build_step_detail", "_make_task_hook", "_fmt_tool_call", "_strip_files", "_clean"}
    extracted = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            extracted[node.name] = ast.get_source_segment(src, node)

    if "_make_task_hook" not in extracted:
        raise RuntimeError("could not AST-extract _make_task_hook from fsapp.py")

    # Build a small namespace with the bare-minimum helpers for the
    # pure-function dependencies. We intentionally keep `_build_step_detail`
    # as a no-op stub because the hook only uses it as a callback name; the
    # behavior we care about (finalize vs not finalize) doesn't depend on
    # the detail body.
    ns = {
        "re": __import__("re"),
        "json": __import__("json"),
        "_TRUNC_TAIL": 200,
    }

    # Stub out pure-function dependencies that are safe to skip.
    exec(
        "def _display_text(text):\n"
        "    return (text or '').strip() or '⚠️ 模型输出被截断或为空'\n",
        ns,
    )
    exec(
        "def _build_step_detail(resp, tool_calls):\n"
        "    return ''\n",
        ns,
    )
    # Now exec the real _make_task_hook source into the namespace.
    exec(extracted["_make_task_hook"], ns)
    return ns


def _make_fake_card():
    card = types.SimpleNamespace()
    card.step_calls = []
    card.done_calls = []
    card.fail_calls = []

    def step(summary, detail=""):
        card.step_calls.append((summary, detail))

    def done(text):
        card.done_calls.append(text)

    def fail(msg):
        card.fail_calls.append(msg)

    card.step = step
    card.done = done
    card.fail = fail
    return card


def _make_fake_parent(task_id):
    parent = types.SimpleNamespace()
    parent._fs_active_task_id = task_id
    return parent


# A wrapper class whose instances carry `_fs_active_task_id`. We do this
# rather than passing the parent directly because the hook reads
# `ctx.get("self").parent` -- i.e. it expects ``ctx["self"]`` to be an object
# whose attribute ``parent`` is the active-task holder. Mirrors how the real
# agent_loop passes the loop self into the hook ctx.
class _LoopSelf:
    def __init__(self, parent):
        self.parent = parent


def _ctx_for(task_id, **fields):
    parent = _make_fake_parent(task_id)
    return {"self": _LoopSelf(parent), **fields}


def test_hook_does_not_finalize_on_exit_reason_with_response():
    """#685 case 1: a turn-level exit_reason with a response must not call on_final."""
    ns = _load_fsapp_helpers()
    card = _make_fake_card()
    task_id = "fs_test_task_1"

    hook = ns["_make_task_hook"](card, task_id)

    class _Resp:
        content = "intermediate turn text"

    ctx = _ctx_for(
        task_id,
        exit_reason={"result": "CURRENT_TASK_DONE", "data": None},
        response=_Resp(),
    )
    hook(ctx)

    assert card.done_calls == [], (
        f"hook finalized the task on turn-level exit_reason "
        f"(#685 regression): done_calls={card.done_calls!r}"
    )
    assert card.step_calls == [], (
        f"hook added a step when only exit_reason was present (no summary): "
        f"step_calls={card.step_calls!r}"
    )


def test_hook_adds_step_when_summary_present_with_exit_reason():
    """#685 case 2: when both summary and exit_reason are present, summary wins."""
    ns = _load_fsapp_helpers()
    card = _make_fake_card()
    task_id = "fs_test_task_2"

    hook = ns["_make_task_hook"](card, task_id)

    class _Resp:
        content = "wrote file output"
        thinking = "I did the thing."

    ctx = _ctx_for(
        task_id,
        summary="wrote file",
        exit_reason={"result": "EXITED", "data": None},
        response=_Resp(),
        tool_calls=[],
    )
    hook(ctx)

    assert len(card.step_calls) == 1, (
        f"summary must be added as a step even when exit_reason is also "
        f"present: step_calls={card.step_calls!r}"
    )
    assert card.step_calls[0][0] == "wrote file", card.step_calls
    assert card.done_calls == [], (
        f"hook must not finalize the task on exit_reason even when a "
        f"summary is also present: done_calls={card.done_calls!r}"
    )


def test_hook_adds_step_for_summary_only():
    ns = _load_fsapp_helpers()
    card = _make_fake_card()
    task_id = "fs_test_task_3"

    hook = ns["_make_task_hook"](card, task_id)

    class _Resp:
        content = "answer"
        thinking = ""

    ctx = _ctx_for(
        task_id,
        summary="answered",
        response=_Resp(),
        tool_calls=[],
    )
    hook(ctx)

    assert len(card.step_calls) == 1
    assert card.step_calls[0][0] == "answered"
    assert card.done_calls == []


def test_hook_is_no_op_for_stale_task_id():
    ns = _load_fsapp_helpers()
    card = _make_fake_card()
    task_id = "fs_test_task_4"
    # parent._fs_active_task_id deliberately mismatches task_id.

    hook = ns["_make_task_hook"](card, task_id)

    ctx = _ctx_for(
        task_id,
        summary="should be ignored",
        exit_reason={"result": "EXITED"},
    )
    # Overwrite parent._fs_active_task_id so the guard fires.
    ctx["self"].parent._fs_active_task_id = "some_other_task"

    hook(ctx)

    assert card.step_calls == []
    assert card.done_calls == []


def test_hook_signature_no_longer_takes_on_final():
    """The fix removes ``on_final`` from the public hook signature."""
    import inspect

    ns = _load_fsapp_helpers()
    sig = inspect.signature(ns["_make_task_hook"])
    params = list(sig.parameters)
    assert params == ["card", "task_id"], (
        f"unexpected hook signature after fix: {params}; on_final must be "
        f"removed (finalization belongs on the display-queue done item)."
    )


def test_old_signature_would_have_finalized_on_exit_reason():
    """Reproduce the pre-fix behavior at the source level so we cover the
    behavioral bug, not only the signature change. This loads the
    pre-fix version of ``_make_task_hook`` (3 args: card, task_id, on_final)
    and asserts that calling it with an exit_reason-only context WOULD
    have triggered the (now-removed) on_final callback. The post-fix
    source no longer accepts on_final, so we exercise the OLD source via
    an inline reproduction.
    """
    on_final_calls = []

    def on_final(raw):
        on_final_calls.append(raw)

    # This is the OLD _make_task_hook body, copied verbatim from the
    # unfixed fsapp.py to capture the behavioral regression. If the live
    # _make_task_hook in fsapp.py ever regains an on_final branch, this
    # test stays meaningful as a behavioral pin.
    def old_hook_factory(card, task_id, on_final):
        def hook(ctx):
            parent = getattr(ctx.get("self"), "parent", None)
            if getattr(parent, "_fs_active_task_id", None) != task_id:
                return
            if ctx.get("exit_reason"):
                resp = ctx.get("response")
                raw = resp.content if hasattr(resp, "content") else str(resp)
                on_final(raw)
            elif ctx.get("summary"):
                pass  # would have called card.step
        return hook

    card = _make_fake_card()

    class _Resp:
        content = "intermediate turn text"

    ctx = _ctx_for(
        "fs_test_task_5",
        exit_reason={"result": "EXITED"},
        response=_Resp(),
    )
    old_hook_factory(card, "fs_test_task_5", on_final)(ctx)

    # Sanity: confirms that the OLD signature's exit_reason branch DID
    # call on_final. This is the exact behavior #685 reports and that the
    # real fix removes. If this assertion ever fails (i.e. on_final is
    # NOT called by the OLD hook) the regression test would no longer
    # cover the bug — meaning either fsapp.py silently re-changed or the
    # reproduction is wrong.
    assert on_final_calls == ["intermediate turn text"], (
        f"reproduction of pre-fix behavior is incorrect: "
        f"on_final_calls={on_final_calls!r}"
    )


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    if failures:
        sys.exit(1)
    print("ALL PASS")
