"""Regression tests for multimodal image passthrough (issue #813, item A-1).

put_task() has always accepted images and every frontend passes them (fsapp
downloads Feishu images to disk and forwards the paths; desktop_bridge and
tui_v3 forward paths as well), but agentmain.run() never handed them to
agent_runner_loop — the first user turn stayed plain text and images were
silently dropped. Two downstream drop points are pinned here too:

- NativeToolClient.chat()'s whitespace filter dropped *every* block lacking
  non-blank text, image blocks included.
- _to_responses_input() only understood OpenAI-style image_url blocks, so
  Claude-style {"type": "image", "source": {...}} blocks vanished on the
  Responses API path.
"""
import ast
import base64
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# test_bridge_sessions.py installs empty module stubs via sys.modules.setdefault;
# under full-suite import order it runs first, so evict them to exercise the
# real implementations here.
for _stubbed in ("llmcore", "agentmain", "agent_loop"):
    sys.modules.pop(_stubbed, None)

import llmcore


# ---------------------------------------------------------------------------
# _to_responses_input: Claude-style image blocks -> input_image
# ---------------------------------------------------------------------------

class TestResponsesInputImageBlocks:
    """The Responses API converter must carry image blocks through."""

    def test_base64_image_block_becomes_input_image(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png", "data": "QUJD"}},
        ]}]
        assert llmcore._to_responses_input(msgs) == [{"role": "user", "content": [
            {"type": "input_text", "text": "what is this?"},
            {"type": "input_image", "image_url": "data:image/png;base64,QUJD"},
        ]}]

    def test_url_source_image_block_becomes_input_image(self):
        msgs = [{"role": "user", "content": [
            {"type": "image", "source": {"type": "url", "url": "https://example.com/a.png"}},
        ]}]
        out = llmcore._to_responses_input(msgs)
        assert out[0]["content"] == [
            {"type": "input_image", "image_url": "https://example.com/a.png"}]

    def test_openai_style_image_url_block_still_works(self):
        """Pre-existing branch: OpenAI-style image_url must not regress."""
        msgs = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}},
        ]}]
        out = llmcore._to_responses_input(msgs)
        assert out[0]["content"] == [
            {"type": "input_image", "image_url": "https://example.com/b.png"}]

    def test_assistant_image_blocks_are_ignored(self):
        msgs = [{"role": "assistant", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
            {"type": "text", "text": "seen"},
        ]}]
        out = llmcore._to_responses_input(msgs)
        assert out[0]["content"] == [{"type": "output_text", "text": "seen"}]

    def test_malformed_image_blocks_are_ignored(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "hi"},
            {"type": "image"},                                    # no source at all
            {"type": "image", "source": {}},                      # empty source
            {"type": "image", "source": {"type": "base64"}},      # no data
            {"type": "image", "source": {"type": "url"}},         # no url
        ]}]
        out = llmcore._to_responses_input(msgs)
        assert out[0]["content"] == [{"type": "input_text", "text": "hi"}]


# ---------------------------------------------------------------------------
# _drop_blank_text_blocks: only blank *text* may be dropped
# ---------------------------------------------------------------------------

class TestDropBlankTextBlocks:
    """The whitespace filter must not eat image/tool_result blocks."""

    def test_blank_text_blocks_dropped(self):
        blocks = [{"type": "text", "text": "  \n\t "},
                  {"type": "text", "text": "keep me"}]
        assert llmcore._drop_blank_text_blocks(blocks) == [{"type": "text", "text": "keep me"}]

    def test_image_blocks_kept(self):
        img = {"type": "image", "source": {"type": "base64",
                                           "media_type": "image/png", "data": "QUJD"}}
        assert llmcore._drop_blank_text_blocks([img]) == [img]

    def test_tool_result_blocks_kept(self):
        tr = {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}
        assert llmcore._drop_blank_text_blocks([tr]) == [tr]

    def test_empty_input(self):
        assert llmcore._drop_blank_text_blocks([]) == []

    def test_mixed_blocks(self):
        blank = {"type": "text", "text": ""}
        img = {"type": "image", "source": {"type": "base64",
                                           "media_type": "image/jpeg", "data": "QUJD"}}
        keep = {"type": "text", "text": "hello"}
        assert llmcore._drop_blank_text_blocks([blank, img, keep]) == [img, keep]


# ---------------------------------------------------------------------------
# NativeToolClient.chat: image blocks must reach backend.ask
# ---------------------------------------------------------------------------

class _FakeBackend:
    """Minimal stand-in for a native session backend."""

    def __init__(self):
        self.name = "fake"
        self.system = ""
        self.tools = None
        self.history = []
        self.asked = []

    def ask(self, msg):
        self.asked.append(msg)
        return
        yield  # pragma: no cover - generator so chat()'s next() hits StopIteration


class TestNativeToolClientChatKeepsImages:
    def test_image_blocks_reach_backend_ask(self):
        client = llmcore.NativeToolClient(_FakeBackend())
        client.log_path = False  # skip file logging
        img = {"type": "image", "source": {"type": "base64",
                                           "media_type": "image/png", "data": "QUJD"}}
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "describe"}, img]}]
        assert list(client.chat(messages=messages)) == []
        assert len(client.backend.asked) == 1
        content = client.backend.asked[0]["content"]
        assert {"type": "text", "text": "describe"} in content
        assert img in content

    def test_blank_text_still_dropped_end_to_end(self):
        client = llmcore.NativeToolClient(_FakeBackend())
        client.log_path = False
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "   "},
            {"type": "text", "text": "real"}]}]
        list(client.chat(messages=messages))
        assert client.backend.asked[0]["content"] == [{"type": "text", "text": "real"}]


# ---------------------------------------------------------------------------
# agentmain._multimodal_initial_content: build the first turn's blocks
# ---------------------------------------------------------------------------

class _FakeNativeClient:
    """Stands in for llmcore.NativeToolClient inside the extracted helper."""


def _load_helper():
    """Extract _multimodal_initial_content from agentmain.py via ast (no import)."""
    src = (PROJECT_ROOT / "agentmain.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_multimodal_initial_content":
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_VISION_MIMES" for t in node.targets):
            nodes.append(node)
    assert nodes, "_multimodal_initial_content not found in agentmain.py"
    ns = {"NativeToolClient": _FakeNativeClient}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<agentmain-extract>", "exec"), ns)
    return ns["_multimodal_initial_content"], ns


class TestMultimodalInitialContent:
    def setup_method(self):
        self.helper, self.ns = _load_helper()

    def test_no_images_returns_none(self):
        assert self.helper("q", [], _FakeNativeClient()) is None
        assert self.helper("q", None, _FakeNativeClient()) is None

    def test_non_native_client_returns_none(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"x")
        # Only NativeToolClient backends understand image blocks; other clients
        # must keep the old plain-text behaviour.
        assert self.helper("q", [str(p)], object()) is None

    def test_builds_text_then_image_blocks(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n-fake")
        blocks = self.helper("describe this", [str(p)], _FakeNativeClient())
        assert blocks[0] == {"type": "text", "text": "describe this"}
        img = blocks[1]
        assert img["type"] == "image"
        assert img["source"]["type"] == "base64"
        assert img["source"]["media_type"] == "image/png"
        assert base64.b64decode(img["source"]["data"]) == b"\x89PNG\r\n\x1a\n-fake"

    def test_unknown_extension_falls_back_to_png(self, tmp_path):
        p = tmp_path / "a.unknownext"
        p.write_bytes(b"x")
        blocks = self.helper("q", [str(p)], _FakeNativeClient())
        assert blocks[1]["source"]["media_type"] == "image/png"

    def test_non_vision_mime_becomes_text_reference(self, tmp_path):
        p = tmp_path / "a.svg"
        p.write_text("<svg/>", encoding="utf-8")
        blocks = self.helper("q", [str(p)], _FakeNativeClient())
        assert blocks[1] == {"type": "text", "text": f"[attached file: {p}]"}

    def test_unreadable_path_becomes_error_text(self, tmp_path):
        # A missing/unreadable attachment must surface as text, never vanish
        # silently — silent drops are exactly what this issue is about.
        blocks = self.helper("q", [str(tmp_path / "gone.png")], _FakeNativeClient())
        assert blocks[0] == {"type": "text", "text": "q"}
        assert blocks[1]["type"] == "text"
        assert "gone.png" in blocks[1]["text"]

    def test_read_failure_becomes_error_text(self, tmp_path):
        def boom(*a, **k):
            raise OSError("permission denied")
        self.ns["open"] = boom
        blocks = self.helper("q", [str(tmp_path / "a.png")], _FakeNativeClient())
        assert blocks[1]["type"] == "text"
        assert "permission denied" in blocks[1]["text"]

    def test_dict_shaped_entries_supported(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"x")
        blocks = self.helper("q", [{"name": "a.png", "path": str(p)}], _FakeNativeClient())
        assert blocks[1]["type"] == "image"


# ---------------------------------------------------------------------------
# agentmain.run() wiring: images must reach agent_runner_loop
# ---------------------------------------------------------------------------

class TestAgentmainWiring:
    def test_agent_runner_loop_receives_initial_user_content(self):
        src = (PROJECT_ROOT / "agentmain.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        run_fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "run")
        calls = [n for n in ast.walk(run_fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "agent_runner_loop"]
        assert calls, "agent_runner_loop call not found in run()"
        kwargs = {kw.arg: kw.value for kw in calls[0].keywords}
        assert "initial_user_content" in kwargs, (
            "run() must forward images via initial_user_content")
        value = kwargs["initial_user_content"]
        assert isinstance(value, ast.Call) and value.func.id == "_multimodal_initial_content"
        all_args = list(value.args) + [kw.value for kw in value.keywords]
        get_calls = [a for a in all_args
                     if isinstance(a, ast.Call) and getattr(a.func, "attr", None) == "get"]
        assert get_calls, "images must be read from the task dict (task.get('images'))"
