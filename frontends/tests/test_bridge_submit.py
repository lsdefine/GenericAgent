"""Unit tests for desktop_bridge.py submit_prompt path-prepend logic and add_message.

Tests the core file-attachment contract: files_meta → agent_prompt path prepend.
Run: pytest frontends/tests/test_bridge_submit.py -v
"""
import json


class TestPathPrepend:
    """Test the agent_prompt construction logic from submit_prompt."""

    @staticmethod
    def _build_agent_prompt(prompt: str, files_meta: list | None) -> str:
        """Replicate the path prepend logic from desktop_bridge.py submit_prompt."""
        agent_prompt = prompt
        if files_meta:
            paths = [f["path"] for f in files_meta if f.get("path")]
            if paths:
                agent_prompt = " ".join(paths) + "\n" + prompt
        return agent_prompt

    def test_single_file_prepend(self):
        prompt = "Analyze this file"
        files = [{"name": "data.csv", "path": "/tmp/uploads/data.csv", "size": 1024}]
        result = self._build_agent_prompt(prompt, files)
        assert result == "/tmp/uploads/data.csv\nAnalyze this file"

    def test_multiple_files_prepend(self):
        prompt = "Compare these"
        files = [
            {"name": "a.py", "path": "/tmp/a.py", "size": 100},
            {"name": "b.py", "path": "/tmp/b.py", "size": 200},
            {"name": "c.py", "path": "/tmp/c.py", "size": 300},
        ]
        result = self._build_agent_prompt(prompt, files)
        assert result == "/tmp/a.py /tmp/b.py /tmp/c.py\nCompare these"

    def test_no_files_meta_unchanged(self):
        prompt = "Just a question"
        assert self._build_agent_prompt(prompt, None) == prompt
        assert self._build_agent_prompt(prompt, []) == prompt

    def test_files_without_path_skipped(self):
        prompt = "Check files"
        files = [
            {"name": "good.txt", "path": "/tmp/good.txt"},
            {"name": "bad.txt"},  # no path
            {"name": "empty.txt", "path": ""},  # empty path
        ]
        result = self._build_agent_prompt(prompt, files)
        assert result == "/tmp/good.txt\nCheck files"

    def test_path_with_spaces(self):
        prompt = "Read it"
        files = [{"name": "my report.txt", "path": "/tmp/desktop_uploads/my report.txt"}]
        result = self._build_agent_prompt(prompt, files)
        assert "/tmp/desktop_uploads/my report.txt" in result

    def test_path_with_cjk(self):
        prompt = "分析这个"
        files = [{"name": "报告.csv", "path": "/tmp/desktop_uploads/报告.csv"}]
        result = self._build_agent_prompt(prompt, files)
        assert result.startswith("/tmp/desktop_uploads/报告.csv\n")

    def test_empty_prompt_with_files(self):
        prompt = ""
        files = [{"name": "f.txt", "path": "/tmp/f.txt"}]
        result = self._build_agent_prompt(prompt, files)
        assert result == "/tmp/f.txt\n"


class TestAddMessageExtra:
    """Test that add_message stores extra fields correctly."""

    @staticmethod
    def _simulate_add_message(role: str, content: str, **extra) -> dict:
        """Replicate add_message logic from AgentManager."""
        msg = {
            "id": 1,
            "role": role,
            "content": content,
            "ts": 1000.0,
        }
        msg.update(extra)
        return msg

    def test_files_stored_in_message(self):
        files_meta = [{"name": "x.py", "path": "/tmp/x.py", "size": 512}]
        msg = self._simulate_add_message("user", "hello", files=files_meta)
        assert msg["files"] == files_meta

    def test_images_stored_in_message(self):
        image_metas = [{"name": "pic.png", "path": "/tmp/pic.png"}]
        msg = self._simulate_add_message("user", "see this", images=image_metas)
        assert msg["images"] == image_metas

    def test_display_stored_separately(self):
        msg = self._simulate_add_message("user", "full prompt with paths", display="clean display text")
        assert msg["display"] == "clean display text"
        assert msg["content"] == "full prompt with paths"

    def test_no_extra_fields_minimal(self):
        msg = self._simulate_add_message("assistant", "response")
        assert "files" not in msg
        assert "images" not in msg
        assert "display" not in msg

    def test_combined_files_and_images(self):
        msg = self._simulate_add_message(
            "user", "both",
            files=[{"name": "f.txt", "path": "/tmp/f.txt"}],
            images=[{"name": "i.png", "path": "/tmp/i.png"}],
        )
        assert len(msg["files"]) == 1
        assert len(msg["images"]) == 1


class TestImagePathExtraction:
    """Test image_paths extraction from image_metas (used for _patch_chat_for_images)."""

    def test_extracts_paths(self):
        image_metas = [
            {"name": "a.png", "path": "/tmp/a.png"},
            {"name": "b.jpg", "path": "/tmp/b.jpg"},
        ]
        image_paths = [m["path"] for m in (image_metas or []) if m.get("path")]
        assert image_paths == ["/tmp/a.png", "/tmp/b.jpg"]

    def test_none_metas(self):
        image_metas = None
        image_paths = [m["path"] for m in (image_metas or []) if m.get("path")]
        assert image_paths == []

    def test_skips_entries_without_path(self):
        image_metas = [
            {"name": "a.png", "path": "/tmp/a.png"},
            {"name": "broken.png"},
        ]
        image_paths = [m["path"] for m in (image_metas or []) if m.get("path")]
        assert image_paths == ["/tmp/a.png"]


class TestSessionFiltering:
    """Test the tui_ prefix filter for conductor sessions."""

    def test_filters_tui_prefix(self):
        sessions = [
            {"id": "abc123", "title": "Chat"},
            {"id": "tui_worker_1", "title": "Worker"},
            {"id": "def456", "title": "Another"},
            {"id": "tui_conductor_main", "title": "Main"},
        ]
        filtered = [s for s in sessions if not s["id"].startswith("tui_")]
        assert len(filtered) == 2
        assert all(not s["id"].startswith("tui_") for s in filtered)

    def test_no_tui_sessions_unchanged(self):
        sessions = [{"id": "a"}, {"id": "b"}]
        filtered = [s for s in sessions if not s["id"].startswith("tui_")]
        assert len(filtered) == 2

    def test_all_tui_sessions_empty_result(self):
        sessions = [{"id": "tui_x"}, {"id": "tui_y"}]
        filtered = [s for s in sessions if not s["id"].startswith("tui_")]
        assert len(filtered) == 0


class TestRunAgentTurnScope:
    """Guard tests: run_agent_turn must NOT reference variables from submit_prompt's scope.

    These tests parse the actual bridge source to catch NameError regressions
    (e.g. referencing 'sid' inside run_agent_turn which runs in a different thread).
    """

    @staticmethod
    def _get_bridge_source() -> str:
        from pathlib import Path
        candidates = [
            Path(__file__).parent.parent / "desktop_bridge.py",
            Path(__file__).parent.parent.parent / "frontends" / "desktop_bridge.py",
        ]
        for p in candidates:
            if p.exists():
                return p.read_text(encoding="utf-8")
        raise FileNotFoundError("desktop_bridge.py not found")

    @staticmethod
    def _extract_method_body(source: str, method_name: str) -> str:
        """Extract a method with Python's parser so multiline signatures remain supported."""
        import ast
        tree = ast.parse(source)
        method = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == method_name
            ),
            None,
        )
        return ast.get_source_segment(source, method) if method is not None else ""

    def test_run_agent_turn_does_not_reference_bare_sid(self):
        """run_agent_turn must use sess.id, never bare 'sid' (which is out of scope)."""
        import re
        source = self._get_bridge_source()
        body = self._extract_method_body(source, "run_agent_turn")
        assert body, "Could not extract run_agent_turn body"
        # Find bare 'sid' references that are NOT part of 'sess.id' or string literals
        bare_sid_refs = re.findall(r'(?<!\.)(?<!\w)sid(?!\w)(?!.*#.*sid)', body)
        # Filter out string contents (inside quotes)
        real_refs = []
        for match in re.finditer(r'(?<!\.)(?<!\w)sid(?!\w)', body):
            pos = match.start()
            # Check we're not inside a string
            before = body[:pos]
            single_q = before.count("'") % 2
            double_q = before.count('"') % 2
            if not single_q and not double_q:
                real_refs.append(match.group())
        assert len(real_refs) == 0, (
            f"run_agent_turn references bare 'sid' {len(real_refs)} time(s). "
            f"Use 'sess.id' instead — 'sid' is only defined in submit_prompt's scope."
        )

    def test_patch_chat_for_images_exists(self):
        """_patch_chat_for_images must exist in bridge — it's the image injection path."""
        source = self._get_bridge_source()
        assert "_patch_chat_for_images" in source, (
            "_patch_chat_for_images method missing from desktop_bridge.py — "
            "image uploads will silently fail (agent won't see images)"
        )

    def test_submit_prompt_separates_agent_prompt_from_stored_message(self):
        """submit_prompt must store clean prompt in message but pass paths to agent."""
        source = self._get_bridge_source()
        body = self._extract_method_body(source, "submit_prompt")
        assert body, "Could not extract submit_prompt body"
        # Must have agent_prompt as a separate variable
        assert "agent_prompt" in body, (
            "submit_prompt must use 'agent_prompt' (with paths) separate from 'prompt' "
            "(clean, stored in message). Otherwise UI shows raw paths to user."
        )
        # add_message must use the clean prompt, not agent_prompt
        import re
        add_msg_call = re.search(r'add_message\(.*?,\s*"user",\s*(\w+)', body)
        assert add_msg_call, "add_message call not found in submit_prompt"
        arg = add_msg_call.group(1)
        assert arg == "prompt", (
            f"add_message stores '{arg}' but should store 'prompt' (clean text). "
            f"agent_prompt (with file paths) goes only to run_agent_turn."
        )

    def test_image_paths_passed_to_run_agent_turn(self):
        """submit_prompt must extract image_paths and pass to run_agent_turn thread."""
        source = self._get_bridge_source()
        body = self._extract_method_body(source, "submit_prompt")
        assert "image_paths" in body, (
            "submit_prompt must extract image_paths from image_metas and pass to "
            "run_agent_turn. Without this, _patch_chat_for_images receives None."
        )
