from types import SimpleNamespace

from ga import GenericAgentHandler


class DummyResponse:
    content = "<summary>read plan sop</summary>"


def make_handler(tmp_path):
    parent = SimpleNamespace(task_dir=str(tmp_path), verbose=False, _turn_end_hooks={})
    return GenericAgentHandler(parent, cwd=str(tmp_path))


def exhaust_generator(gen):
    try:
        while True:
            next(gen)
    except StopIteration as exc:
        return exc.value


def test_reading_plan_sop_marks_pending(tmp_path):
    plan_sop = tmp_path / "memory" / "plan_sop.md"
    plan_sop.parent.mkdir()
    plan_sop.write_text("# Plan Mode SOP\n", encoding="utf-8")
    handler = make_handler(tmp_path)

    outcome = exhaust_generator(handler.do_file_read({"path": "memory/plan_sop.md"}, DummyResponse()))

    assert outcome.data.startswith("由于设置了show_linenos")
    assert handler.working["plan_mode_pending"]["sop_path"] == str(plan_sop)


def test_pending_plan_guard_blocks_next_prompt_until_entered(tmp_path):
    handler = make_handler(tmp_path)
    handler.working["plan_mode_pending"] = {"sop_path": "memory/plan_sop.md", "turn": 1}

    prompt = handler.turn_end_callback(
        DummyResponse(),
        [{"tool_name": "file_read", "args": {"path": "memory/plan_sop.md"}}],
        [],
        1,
        "NEXT",
        None,
    )

    assert "[Plan Mode Guard]" in prompt
    assert "handler.enter_plan_mode" in prompt
    assert prompt.endswith("NEXT")
    assert "plan_mode_pending" in handler.working


def test_enter_plan_mode_clears_pending(tmp_path):
    handler = make_handler(tmp_path)
    handler.working["plan_mode_pending"] = {"sop_path": "memory/plan_sop.md", "turn": 1}

    assert handler.enter_plan_mode("./plan_demo/plan.md") == "./plan_demo/plan.md"

    assert handler.working["in_plan_mode"] == "./plan_demo/plan.md"
    assert "plan_mode_pending" not in handler.working
