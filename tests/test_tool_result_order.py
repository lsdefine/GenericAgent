import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llmcore


class _FakeBackend:
    """最小 backend：ask() 返回一个只产出 MockResponse 的生成器。"""
    name = "fake"
    model = "fake-model"
    system = ""
    tools = None
    history = []

    def __init__(self):
        self.sent = None

    def ask(self, merged):
        self.sent = merged

        def _gen():
            yield  # 先产一个 chunk，让 chat() 进入正常迭代
            return llmcore.MockResponse("", "ok", [], "raw")

        return _gen()


def _capture_prompt(monkeypatch):
    logs = []
    monkeypatch.setattr(llmcore, "_write_llm_log",
                        lambda label, content, log_path=None, model="": logs.append((label, content)))
    return logs


def _prompt_payload(logs):
    import json
    for label, content in logs:
        if label == "Prompt":
            # content 形如 '{"role": "user", "content": [\n{b},\n{b}]}'
            return json.loads(content)
    raise AssertionError("未捕获 Prompt 日志")


def test_orphan_tool_results_keep_order(monkeypatch):
    """空 tool_use_id 的多个结果必须按原顺序，且排在用户正文之后。"""
    logs = _capture_prompt(monkeypatch)
    client = llmcore.NativeToolClient(_FakeBackend())
    msgs = [{
        "role": "user",
        "content": "USER_TEXT",
        "tool_results": [
            {"tool_use_id": "", "content": "R1"},
            {"tool_use_id": "", "content": "R2"},
            {"tool_use_id": "call_X", "content": "R3"},
        ],
    }]
    for _ in client.chat(messages=msgs, tools=None):
        pass

    payload = _prompt_payload(logs)
    blocks = payload["content"]

    # 结构化结果在最前
    assert blocks[0]["type"] == "tool_result" and blocks[0]["tool_use_id"] == "call_X", blocks

    texts = [b.get("text", "") for b in blocks[1:] if b.get("type") == "text"]
    assert "USER_TEXT" in texts, texts
    # 裸文本结果按 R1,R2 原顺序，且都在 USER_TEXT 之后
    i_user = texts.index("USER_TEXT")
    tails = [t for t in texts[i_user + 1:] if t.startswith("<tool_result>")]
    assert tails == ["<tool_result>R1</tool_result>", "<tool_result>R2</tool_result>"], texts


def test_no_orphan_keeps_previous_shape(monkeypatch):
    """全部有 id 时行为不变：只有 tool_result 块 + 正文。"""
    logs = _capture_prompt(monkeypatch)
    client = llmcore.NativeToolClient(_FakeBackend())
    msgs = [{
        "role": "user",
        "content": "USER_TEXT",
        "tool_results": [{"tool_use_id": "call_A", "content": "RA"}],
    }]
    for _ in client.chat(messages=msgs, tools=None):
        pass

    blocks = _prompt_payload(logs)["content"]
    assert blocks[0] == {"type": "tool_result", "tool_use_id": "call_A", "content": "RA"}, blocks
    assert not any(b.get("text", "").startswith("<tool_result>") for b in blocks), blocks


def test_pending_ids_filled(monkeypatch):
    """未回填的 pending id 要补空 content，且不影响顺序。"""
    logs = _capture_prompt(monkeypatch)
    backend = _FakeBackend()
    backend.history = [{"role": "user", "content": "prev"}]   # 非空: 否则 chat() 会清空 pending ids
    client = llmcore.NativeToolClient(backend)
    client._pending_tool_ids = ["call_P"]
    for _ in client.chat(messages=[{"role": "user", "content": "hi"}], tools=None):
        pass

    blocks = _prompt_payload(logs)["content"]
    assert {"type": "tool_result", "tool_use_id": "call_P", "content": ""} in blocks, blocks
