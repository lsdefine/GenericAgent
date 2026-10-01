"""Tests for blank-response diagnostics + severity-preserving TUI rendering (#815).

ga.py and tui_v3.py have heavy import side effects, so the helpers under test
are extracted from source via ast/exec (same pattern as test_bridge_utils.py).
Run: pytest frontends/tests/test_blank_response_diagnostics.py -v
"""
import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
_GA_SRC = (ROOT / "ga.py").read_text(encoding="utf-8")
_TUI_SRC = (ROOT / "frontends" / "tui_v3.py").read_text(encoding="utf-8")


def _load_ga_helpers(names):
    tree = ast.parse(_GA_SRC)
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    namespace = {"re": re, "sys": sys, "urlparse": urlparse}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ga.py", "exec"), namespace)
    return namespace


def _load_tui_helpers(names):
    tree = ast.parse(_TUI_SRC)
    nodes = [
        node for node in tree.body
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names)
        or (isinstance(node, ast.Assign)
            and {t.id for t in node.targets if isinstance(t, ast.Name)} & names)
    ]
    namespace = {"re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "tui_v3.py", "exec"), namespace)
    return namespace


_GA = _load_ga_helpers({"describe_blank_response", "_url_host"})
_TUI = _load_tui_helpers({"_ACTION_RE", "_SEVERITY_RE", "_severity_sub"})
describe_blank_response = _GA["describe_blank_response"]
url_host = _GA["_url_host"]


class TestDescribeBlankResponse:
    def test_whitespace_only_payload_with_text_block(self):
        resp = SimpleNamespace(raw="[{'type': 'text', 'text': ' '}]", content=" ", thinking="")
        assert describe_blank_response(resp, " ", "") == (
            "kind=whitespace_only len(content)=1 len(thinking)=0 blocks=text"
        )

    def test_empty_payload_has_no_blocks_part(self):
        resp = SimpleNamespace(raw="[]", content="", thinking="")
        assert describe_blank_response(resp, "", "") == (
            "kind=empty_payload len(content)=0 len(thinking)=0"
        )

    def test_blocks_are_deduped_and_sorted(self):
        raw = "[{'type': 'thinking', 'thinking': 'x'}, {'type': 'text', 'text': ' '}]"
        resp = SimpleNamespace(raw=raw, content="\n ", thinking="")
        diag = describe_blank_response(resp, "\n ", "")
        assert "kind=whitespace_only" in diag
        assert "blocks=text+thinking" in diag

    def test_no_raw_means_no_blocks_part(self):
        resp = SimpleNamespace(raw="", content=" ", thinking="")
        assert "blocks" not in describe_blank_response(resp, " ", "")

    def test_both_blank_but_whitespace_reports_both_lengths(self):
        resp = SimpleNamespace(raw="", content="   ", thinking="  ")
        assert describe_blank_response(resp, "   ", "  ") == (
            "kind=whitespace_only len(content)=3 len(thinking)=2"
        )

    def test_backend_appends_model_and_host(self):
        backend = SimpleNamespace(model="gpt-4o", api_base="https://api.openai.com/v1")
        resp = SimpleNamespace(raw="", content=" ", thinking="")
        assert describe_blank_response(resp, " ", "", backend).endswith(
            "model=gpt-4o host=api.openai.com"
        )

    def test_host_never_leaks_credentials(self):
        backend = SimpleNamespace(model="m", api_base="https://user:s3cret@relay.example.com:8443/v1")
        resp = SimpleNamespace(raw="", content=" ", thinking="")
        diag = describe_blank_response(resp, " ", "", backend)
        assert "host=relay.example.com" in diag
        assert "s3cret" not in diag

    def test_missing_model_falls_back_to_question_mark(self):
        backend = SimpleNamespace(model=None, api_base="")
        resp = SimpleNamespace(raw="", content=" ", thinking="")
        assert describe_blank_response(resp, " ", "", backend).endswith("model=? host=unknown")


class TestUrlHost:
    def test_extracts_hostname(self):
        assert url_host("https://api.openai.com/v1") == "api.openai.com"

    def test_drops_port_and_userinfo(self):
        assert url_host("http://user:pw@relay.example.com:8443/v1") == "relay.example.com"

    def test_garbage_input_returns_unknown(self):
        assert url_host("") == "unknown"
        assert url_host("not a url") == "unknown"


class TestSeverityRendering:
    def test_action_info_debug_collapse_to_neutral_bullet(self):
        out = _TUI["_ACTION_RE"].sub('· ', "[Action] run\n[Info] hi\n[Debug] x")
        assert out == "· run\n· hi\n· x"

    def test_severity_tags_keep_their_label(self):
        out = _TUI["_SEVERITY_RE"].sub(_TUI["_severity_sub"], "[Warn] a\n[Error] b\n[Warning] c")
        assert out == "· [Warn] a\n· [Error] b\n· [Warning] c"

    def test_regexes_are_disjoint(self):
        for tag in ("Warn", "Warning", "Error"):
            assert _TUI["_ACTION_RE"].search(f"[{tag}] x") is None
            assert _TUI["_SEVERITY_RE"].search(f"[{tag}] x") is not None
        for tag in ("Action", "Status", "Info", "Debug"):
            assert _TUI["_ACTION_RE"].search(f"[{tag}] x") is not None
            assert _TUI["_SEVERITY_RE"].search(f"[{tag}] x") is None

    def test_full_pipeline_matches_issue_815_example(self):
        raw = "[Info] working\n[Warn] Empty LLM response (1/3); retrying\n[Action] run"
        out = _TUI["_SEVERITY_RE"].sub(
            _TUI["_severity_sub"], _TUI["_ACTION_RE"].sub('· ', raw))
        assert out == "· working\n· [Warn] Empty LLM response (1/3); retrying\n· run"
