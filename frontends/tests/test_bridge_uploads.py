"""Unit tests for desktop_bridge.py upload/path-safety logic.

Follows the existing bridge testing strategy: replicate pure upload/path logic
without importing the whole desktop_bridge module (which starts services).
Run: pytest frontends/tests/test_bridge_uploads.py -v
"""

from __future__ import annotations

import base64
import re
from pathlib import Path


# Mirrors desktop_bridge._safe_session_dir
def _safe_session_dir(sid: str | None) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]", "", str(sid or ""))
    return s or "_misc"


# Mirrors desktop_bridge._session_upload_dir
def _session_upload_dir(upload_root: Path, sid: str) -> Path:
    return upload_root / _safe_session_dir(sid)


# Mirrors the upload_handler naming/path rules.
def _build_upload_path(upload_root: Path, sid: str, name: str, token: str) -> Path:
    safe_name = (name or "file").strip().replace("/", "_").replace("\\", "_") or "file"
    return _session_upload_dir(upload_root, sid) / f"{token}__{safe_name}"


# Mirrors upload_handler decode logic.
def _decode_upload_data(data_url: str) -> bytes:
    if "," in data_url:
        b64 = data_url.split(",", 1)[1]
    else:
        b64 = data_url
    return base64.b64decode(b64)


# Mirrors upload_delete_handler path whitelist.
def _delete_allowed(upload_root: Path, raw_path: str) -> bool:
    target = Path(raw_path).resolve()
    root = upload_root.resolve()
    return root in target.parents


# Mirrors upload_raw_handler path whitelist.
def _raw_allowed(upload_root: Path, raw_path: str) -> bool:
    target = Path(raw_path).resolve()
    try:
        target.relative_to(upload_root.resolve())
        return True
    except (ValueError, OSError):
        return False


# Mirrors upload_raw_handler original filename recovery.
def _original_upload_name(path: Path) -> str:
    return path.name.split("__", 1)[-1]


class TestSafeSessionDir:
    def test_keeps_safe_ascii_chars(self):
        assert _safe_session_dir("abc-DEF_123") == "abc-DEF_123"

    def test_strips_path_traversal_and_spaces(self):
        assert _safe_session_dir(" ../../team notes ") == "teamnotes"

    def test_empty_or_none_falls_back_to_misc(self):
        assert _safe_session_dir("") == "_misc"
        assert _safe_session_dir(None) == "_misc"

    def test_non_ascii_only_sid_falls_back_to_misc(self):
        assert _safe_session_dir("报告/会议") == "_misc"


class TestSessionUploadDir:
    def test_scopes_uploads_under_sanitized_sid(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        actual = _session_upload_dir(root, "../../tui_worker")
        assert actual == root / "tui_worker"

    def test_files_bucket_stays_isolated(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        actual = _session_upload_dir(root, "_files")
        assert actual == root / "_files"


class TestUploadPathConstruction:
    def test_replaces_slashes_in_uploaded_name(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        path = _build_upload_path(root, "session-1", "dir/sub\\name.txt", "abc123def456")
        assert path == root / "session-1" / "abc123def456__dir_sub_name.txt"

    def test_uses_file_when_name_empty(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        path = _build_upload_path(root, "session-1", "   ", "abc123def456")
        assert path.name == "abc123def456__file"


class TestUploadDecode:
    def test_decodes_data_url_payload(self):
        payload = "hello,world".encode("utf-8")
        data_url = "data:text/plain;base64," + base64.b64encode(payload).decode("ascii")
        assert _decode_upload_data(data_url) == payload

    def test_decodes_raw_base64_payload(self):
        payload = b"abc123"
        raw = base64.b64encode(payload).decode("ascii")
        assert _decode_upload_data(raw) == payload


class TestUploadPathSafety:
    def test_delete_allows_file_inside_upload_root(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        target = root / "session-1" / "abc__note.txt"
        target.parent.mkdir(parents=True)
        target.write_text("ok", encoding="utf-8")
        assert _delete_allowed(root, str(target)) is True

    def test_delete_rejects_file_outside_upload_root(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        outside = tmp_path / "outside.txt"
        outside.write_text("nope", encoding="utf-8")
        assert _delete_allowed(root, str(outside)) is False

    def test_raw_allows_file_inside_upload_root(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        target = root / "session-1" / "abc__report.csv"
        target.parent.mkdir(parents=True)
        target.write_text("x,y", encoding="utf-8")
        assert _raw_allowed(root, str(target)) is True

    def test_raw_rejects_path_traversal_outside_upload_root(self, tmp_path: Path):
        root = tmp_path / "desktop_uploads"
        outside = tmp_path / "secret.txt"
        outside.write_text("top secret", encoding="utf-8")
        assert _raw_allowed(root, str(outside)) is False


class TestOriginalUploadName:
    def test_strips_uuid_prefix_from_uploaded_file(self):
        path = Path("/tmp/desktop_uploads/session-1/abc123def456__my report.txt")
        assert _original_upload_name(path) == "my report.txt"

    def test_preserves_cjk_filename(self):
        path = Path("/tmp/desktop_uploads/session-1/abc123def456__报告.csv")
        assert _original_upload_name(path) == "报告.csv"

    def test_filename_without_prefix_returns_name_as_is(self):
        path = Path("/tmp/desktop_uploads/session-1/plain.txt")
        assert _original_upload_name(path) == "plain.txt"
