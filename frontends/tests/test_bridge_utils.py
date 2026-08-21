"""Unit tests for desktop_bridge.py utility functions.

Tests pure functions that don't require agent/session infrastructure.
Run: pytest frontends/tests/test_bridge_utils.py -v
"""
import ast
import os
import shutil
import sys
import re
import time
from pathlib import Path

# Add project root so we can import bridge helpers
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "frontends"))

# Import the functions under test (module-level helpers)
import importlib.util
spec = importlib.util.spec_from_file_location("desktop_bridge", ROOT / "frontends" / "desktop_bridge.py")

# We can't import the whole module (it starts aiohttp etc.) so we extract functions manually
_bridge_source = (ROOT / "frontends" / "desktop_bridge.py").read_text(encoding="utf-8")


def _load_named_helpers(names, namespace):
    tree = ast.parse(_bridge_source)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "desktop_bridge.py", "exec"), namespace)
    return namespace


class TestGaRootBoundary:
    def test_external_core_override_needs_only_agentmain(self, tmp_path, monkeypatch):
        external = tmp_path / "external core"
        external.mkdir()
        (external / "agentmain.py").write_text("# core\n", encoding="utf-8")
        monkeypatch.setenv("GA_ROOT", str(external))
        monkeypatch.setattr(sys, "argv", ["desktop_bridge.py"])

        helpers = _load_named_helpers(
            {"_ga_root_override"},
            {"os": os, "sys": sys, "Path": Path, "Optional": __import__("typing").Optional},
        )

        assert helpers["_ga_root_override"]() == external.resolve()

    def test_invalid_override_falls_back_instead_of_becoming_app_dir(self, tmp_path, monkeypatch):
        missing = tmp_path / "deleted-core"
        monkeypatch.setenv("GA_ROOT", str(missing))
        monkeypatch.setattr(sys, "argv", ["desktop_bridge.py"])
        helpers = _load_named_helpers(
            {"_ga_root_override"},
            {"os": os, "sys": sys, "Path": Path, "Optional": __import__("typing").Optional},
        )

        assert helpers["_ga_root_override"]() is None


class TestMemoryImport:
    def test_backup_overwrite_and_response_add_only(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        (source / "memory").mkdir(parents=True)
        (source / "memory" / "same.md").write_text("new", encoding="utf-8")
        (source / "memory" / "added.md").write_text("added", encoding="utf-8")
        (source / "temp" / "model_responses").mkdir(parents=True)
        (source / "temp" / "model_responses" / "same.json").write_text("new", encoding="utf-8")
        (source / "temp" / "model_responses" / "added.json").write_text("added", encoding="utf-8")
        (target / "memory").mkdir(parents=True)
        (target / "memory" / "same.md").write_text("old", encoding="utf-8")
        (target / "temp" / "model_responses").mkdir(parents=True)
        (target / "temp" / "model_responses" / "same.json").write_text("old", encoding="utf-8")

        helpers = _load_named_helpers(
            {"_import_memory_from"},
            {"Path": Path, "shutil": shutil, "time": time},
        )
        result = helpers["_import_memory_from"](str(source), str(target))

        assert result["memoryCopied"] == 2
        assert result["responsesCopied"] == 1
        assert result["responsesSkipped"] == 1
        assert (target / "memory" / "same.md").read_text(encoding="utf-8") == "new"
        assert (target / "temp" / "model_responses" / "same.json").read_text(encoding="utf-8") == "old"
        backup = Path(result["backupDir"])
        assert (backup / "memory" / "same.md").read_text(encoding="utf-8") == "old"


def _load_empty_turn_helpers():
    tree = ast.parse(_bridge_source)
    wanted = {"_EMPTY_TURN_MICROCOPY", "_get_ui_lang", "empty_turn_fallback"}
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & wanted:
                nodes.append(node)
    namespace = {"Path": Path, "json": json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "desktop_bridge.py", "exec"), namespace)
    return namespace


class TestEmptyTurnFallback:
    def test_uses_english_microcopy(self, tmp_path, monkeypatch):
        (tmp_path / ".ga_desktop_settings.json").write_text('{"lang":"en"}', encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        helpers = _load_empty_turn_helpers()

        assert helpers["empty_turn_fallback"]() == (
            '⚠️ This turn ended without a visible response. You can send "continue" to retry.'
        )

    def test_defaults_to_chinese_for_missing_or_invalid_settings(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        helpers = _load_empty_turn_helpers()
        expected = '⚠️ 这一轮结束了，但没有产出可见回复。你可以发送"继续"重试。'
        assert helpers["empty_turn_fallback"]() == expected

        (tmp_path / ".ga_desktop_settings.json").write_text("not-json", encoding="utf-8")
        assert helpers["empty_turn_fallback"]() == expected

    def test_defaults_to_chinese_for_non_string_language(self, tmp_path, monkeypatch):
        (tmp_path / ".ga_desktop_settings.json").write_text('{"lang":[]}', encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        helpers = _load_empty_turn_helpers()

        assert helpers["empty_turn_fallback"]() == (
            '⚠️ 这一轮结束了，但没有产出可见回复。你可以发送"继续"重试。'
        )


# === strip_final_info_marker ===

_FINAL_INFO_RE = re.compile(r'\n*`{5}\n*\[Info\] Final response to user\.\n*`{5}\s*$')

def strip_final_info_marker(text):
    return _FINAL_INFO_RE.sub('', str(text or ''))


class TestStripFinalInfoMarker:
    def test_removes_marker_at_end(self):
        text = "Hello world\n`````\n[Info] Final response to user.\n`````"
        assert strip_final_info_marker(text) == "Hello world"

    def test_no_marker_unchanged(self):
        text = "Just normal text"
        assert strip_final_info_marker(text) == "Just normal text"

    def test_empty_string(self):
        assert strip_final_info_marker("") == ""

    def test_none_becomes_empty(self):
        # str(None or '') → '' since `or` short-circuits
        assert strip_final_info_marker(None) == ""

    def test_marker_only_in_middle_not_removed(self):
        text = "Before\n`````\n[Info] Final response to user.\n`````\nAfter"
        assert strip_final_info_marker(text) == text


# === normalize_final_turn_segs ===

def normalize_final_turn_segs(full, outputs):
    if not outputs or not isinstance(outputs, (list, tuple)):
        return None
    segs = [strip_final_info_marker(s) for s in outputs]
    full_text = strip_final_info_marker(full)
    if not segs:
        return None
    joined = "".join(segs)
    if full_text.strip() == joined.strip():
        return segs
    if joined and full_text.startswith(joined):
        suffix = full_text[len(joined):]
        if suffix.strip():
            segs[-1] = segs[-1] + suffix
        return segs
    return None


class TestNormalizeFinalTurnSegs:
    def test_exact_match(self):
        segs = normalize_final_turn_segs("AB", ["A", "B"])
        assert segs == ["A", "B"]

    def test_suffix_appended_to_last_seg(self):
        segs = normalize_final_turn_segs("ABC_extra", ["A", "BC"])
        assert segs is not None
        assert segs[-1] == "BC_extra"

    def test_no_match_returns_none(self):
        segs = normalize_final_turn_segs("XYZ", ["A", "B"])
        assert segs is None

    def test_none_outputs_returns_none(self):
        assert normalize_final_turn_segs("text", None) is None

    def test_empty_outputs_returns_none(self):
        assert normalize_final_turn_segs("text", []) is None

    def test_string_outputs_returns_none(self):
        assert normalize_final_turn_segs("text", "not a list") is None

    def test_whitespace_match(self):
        segs = normalize_final_turn_segs("A B ", ["A B "])
        assert segs == ["A B "]


# === _extract_first_timestamp ===

def _extract_first_timestamp(content):
    m = re.search(r'^=== Prompt === (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', content, re.MULTILINE)
    if m:
        try:
            from datetime import datetime
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            pass
    return 0.0


class TestExtractFirstTimestamp:
    def test_extracts_valid_timestamp(self):
        content = "=== Prompt === 2024-06-15 14:30:00\nSome prompt text"
        ts = _extract_first_timestamp(content)
        assert ts > 0
        from datetime import datetime
        expected = datetime(2024, 6, 15, 14, 30, 0).timestamp()
        assert ts == expected

    def test_no_match_returns_zero(self):
        assert _extract_first_timestamp("No timestamp here") == 0.0

    def test_empty_string(self):
        assert _extract_first_timestamp("") == 0.0

    def test_multiline_finds_first(self):
        content = "Some header\n=== Prompt === 2024-01-01 00:00:00\n=== Response === 2024-01-01 00:01:00"
        ts = _extract_first_timestamp(content)
        from datetime import datetime
        assert ts == datetime(2024, 1, 1, 0, 0, 0).timestamp()


# === _next_native_var ===

def _next_native_var(text, protocol):
    proto = str(protocol or "").strip().lower()
    if proto == "claude":
        prefix = "native_claude_config"
    elif proto in ("oai", "openai"):
        prefix = "native_oai_config"
    else:
        raise ValueError("protocol is required: choose 'oai' or 'claude'")
    nums = [0]
    if re.search(rf"^{prefix}\s*=", text, re.M):
        nums.append(0)
    nums.extend(int(m.group(1)) for m in re.finditer(rf"^{prefix}(\d+)\s*=", text, re.M))
    n = max(nums) + 1
    return prefix if n == 1 and not re.search(rf"^{prefix}\s*=", text, re.M) else f"{prefix}{n}"


class TestNextNativeVar:
    def test_first_oai_config(self):
        assert _next_native_var("", "oai") == "native_oai_config"

    def test_first_claude_config(self):
        assert _next_native_var("", "claude") == "native_claude_config"

    def test_increments_when_one_exists(self):
        text = "native_oai_config = {'key': 'xxx'}"
        result = _next_native_var(text, "oai")
        # When base var exists: nums=[0,0], max=0, n=1, but base already exists → prefix1
        assert result == "native_oai_config1"

    def test_increments_past_existing_numbered(self):
        text = "native_claude_config = {}\nnative_claude_config2 = {}\nnative_claude_config3 = {}"
        result = _next_native_var(text, "claude")
        assert result == "native_claude_config4"

    def test_raises_on_invalid_protocol(self):
        import pytest
        with pytest.raises(ValueError, match="protocol is required"):
            _next_native_var("", "gemini")

    def test_openai_alias(self):
        assert _next_native_var("", "openai") == "native_oai_config"


# === _format_py_dict ===

import json

def _format_py_dict(d):
    lines = [f"    '{k}': {json.dumps(v, ensure_ascii=False)}," if isinstance(v, str) else f"    '{k}': {v}," for k, v in d.items()]
    return "{\n" + "\n".join(lines) + "\n}"


class TestFormatPyDict:
    def test_simple_dict(self):
        result = _format_py_dict({"key": "sk-xxx", "model": "gpt-4"})
        assert "'key': \"sk-xxx\"" in result
        assert "'model': \"gpt-4\"" in result
        assert result.startswith("{")
        assert result.endswith("}")

    def test_non_string_values(self):
        result = _format_py_dict({"timeout": 30, "stream": True})
        assert "'timeout': 30," in result
        assert "'stream': True," in result

    def test_empty_dict(self):
        result = _format_py_dict({})
        assert result == "{\n\n}"

    def test_chinese_values_preserved(self):
        result = _format_py_dict({"name": "模型一"})
        assert "模型一" in result


# === _load_plan_baseline ===

def _load_plan_baseline(item, msgs):
    base = int(item.get("plan_scan_baseline", 0) or 0)
    if base >= len(msgs):
        return 0
    return max(0, base)


class TestLoadPlanBaseline:
    def test_valid_baseline(self):
        assert _load_plan_baseline({"plan_scan_baseline": 5}, list(range(10))) == 5

    def test_baseline_exceeds_messages_returns_zero(self):
        assert _load_plan_baseline({"plan_scan_baseline": 20}, list(range(5))) == 0

    def test_missing_key_returns_zero(self):
        assert _load_plan_baseline({}, list(range(10))) == 0

    def test_none_value_returns_zero(self):
        assert _load_plan_baseline({"plan_scan_baseline": None}, list(range(10))) == 0

    def test_negative_clamped_to_zero(self):
        assert _load_plan_baseline({"plan_scan_baseline": -5}, list(range(10))) == 0
