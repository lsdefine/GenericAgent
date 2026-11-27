"""Tests for Feishu task-card rollover (#814).

fsapp.py imports lark_oapi at module load, so _TaskCard and the limit-error
helper are extracted from source via ast/exec (same pattern as
test_bridge_utils.py) and exercised against a fake transport.
Run: pytest frontends/tests/test_fsapp_card_rollover.py -v
"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_FSAPP_SRC = (ROOT / "frontends" / "fsapp.py").read_text(encoding="utf-8")


class FakeTransport:
    """Scriptable stand-in for the lark-oapi transport layer."""

    def __init__(self):
        self.patched = []              # [(msg_id, elements)]
        self.created = []              # [elements]
        self.patch_limit_after = None  # Nth patch onward fails with a card-limit error
        self.create_fail = False
        self.fallback_texts = []

    def card_raw(self, elements):
        return json.dumps({"body": {"elements": elements}}, ensure_ascii=False)

    def send_raw(self, rid, payload, msg_type, rtype):
        elements = json.loads(payload)["body"]["elements"]
        self.created.append(elements)
        return None if self.create_fail else f"msg-{len(self.created)}"

    def patch_result(self, message_id, card_json):
        elements = json.loads(card_json)["body"]["elements"]
        self.patched.append((message_id, elements))
        if self.patch_limit_after is not None and len(self.patched) > self.patch_limit_after:
            return False, True         # 230099-style platform card limit
        return True, False

    def send_message(self, rid, text, receive_id_type="open_id"):
        self.fallback_texts.append(text)


def _load(transport):
    tree = ast.parse(_FSAPP_SRC)
    wanted = {"_TaskCard", "_is_card_limit_error", "_CARD_LIMIT_MARKERS"}
    nodes = [
        n for n in tree.body
        if (isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in wanted)
        or (isinstance(n, ast.Assign)
            and {t.id for t in n.targets if isinstance(t, ast.Name)} & wanted)
    ]
    ns = {
        "_card_raw": transport.card_raw,
        "_send_raw": transport.send_raw,
        "_patch_card_result": transport.patch_result,
        "send_message": transport.send_message,
        "_display_text": lambda t: t or "",
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "fsapp.py", "exec"), ns)
    return ns["_TaskCard"], ns["_is_card_limit_error"]


def _panel_titles(elements):
    return [e["header"]["title"]["content"] for e in elements if e.get("tag") == "collapsible_panel"]


def _header(elements):
    return elements[0]["content"]


def _markdown_texts(elements):
    return [e["content"] for e in elements if e.get("tag") == "markdown"]


class TestNormalFlow:
    def test_single_card_patches_in_place(self):
        t = FakeTransport()
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        card.step("读文件", "detail-1")
        card.step("写文件", "detail-2")
        assert card.msg_id == "msg-1"
        assert [m for m, _ in t.patched] == ["msg-1", "msg-1"]
        assert _panel_titles(t.patched[-1][1]) == ["Turn 1 · 读文件", "Turn 2 · 写文件"]
        assert card.page_no == 1
        assert t.fallback_texts == []

    def test_create_failure_at_start_falls_back_to_text(self):
        t = FakeTransport()
        t.create_fail = True
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        assert t.fallback_texts == ["🤔 思考中..."]


class TestReactiveRollover:
    def test_patch_limit_rolls_over_to_smaller_card(self):
        t = FakeTransport()
        t.patch_limit_after = 1                     # 2nd patch hits the platform limit
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        card.step("s1", "d1")                       # patch #1 ok
        card.step("s2", "d2")                       # patch #2 -> limit -> rollover

        assert card.page_no == 2
        assert card.msg_id == "msg-2"               # new card created
        new_elements = t.created[-1]
        assert _panel_titles(new_elements) == ["Turn 2 · s2"]   # steps cleared: new card is small
        assert "📄 工作卡片 2" in _header(new_elements)
        assert any("上一张工作卡片达到飞书限制" in c for c in _markdown_texts(new_elements))
        assert card.turn_base == 2

    def test_turn_numbering_stays_contiguous_across_cards(self):
        t = FakeTransport()
        t.patch_limit_after = 1
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        card.step("s1", "d1")
        card.step("s2", "d2")                       # rollover happens here
        card.step("s3", "d3")                       # lands on the new card
        assert _panel_titles(t.patched[-1][1]) == ["Turn 2 · s2", "Turn 3 · s3"]

    def test_create_failure_is_treated_as_limit_and_retries(self):
        t = FakeTransport()
        t.create_fail = True
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()                                # create #1 fails -> text fallback
        card.step("s1", "d1")                       # create #2 fails -> limit -> rollover -> create #3
        assert len(t.created) == 3
        assert card.page_no == 2
        assert t.fallback_texts == ["🤔 思考中..."]

    def test_done_rolls_over_and_keeps_final_text(self):
        t = FakeTransport()
        t.patch_limit_after = 1
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        card.step("s1", "d1")
        card.done("最终答案")
        assert t.fallback_texts == []               # recovered via rollover
        assert any("最终答案" in c for c in _markdown_texts(t.created[-1]))

    def test_fail_rolls_over_and_keeps_error_status(self):
        t = FakeTransport()
        t.patch_limit_after = 1
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        card.step("s1", "d1")
        card.fail("boom")
        assert t.fallback_texts == []
        assert "❌ boom" in _header(t.created[-1])

    def test_persistent_failure_falls_back_once_per_boundary(self):
        t = FakeTransport()
        t.create_fail = True
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        card.fail("boom")
        assert t.fallback_texts == ["🤔 思考中...", "❌ boom"]


class TestProactiveRollover:
    def test_threshold_flips_page_before_api_rejects(self):
        t = FakeTransport()
        TaskCard, _ = _load(t)
        card = TaskCard("rid", "open_id")
        card.start()
        for i in range(1, 51):
            card.step(f"s{i}", f"d{i}")
        assert card.page_no == 1                    # 50 steps fit under the threshold
        card.step("s51", "d51")                     # 51st trips the proactive rollover
        assert card.page_no == 2
        assert card.turn_base == 51
        assert _panel_titles(t.created[-1]) == ["Turn 51 · s51"]   # rollover pushed a fresh small card


class TestLimitErrorMarkers:
    def test_platform_limit_codes_detected(self):
        _, is_limit = _load(FakeTransport())
        assert is_limit(230099, "Failed to create card content")
        assert is_limit(11310, "element exceeds the limit")
        assert is_limit("", "Element Exceeds The Limit")   # case-insensitive

    def test_other_errors_are_not_limit(self):
        _, is_limit = _load(FakeTransport())
        assert not is_limit(99991672, "token expired")
        assert not is_limit("", "")
