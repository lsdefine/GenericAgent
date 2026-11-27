"""@-completion index must survive Windows device-name entries.

`bash -c 'some-command > NUL'` creates a *real* file called NUL (bash has no
NUL device).  os.scandir() lists it, but ntpath.abspath("NUL") is
"\\\\.\\NUL", so os.path.relpath() raises

    ValueError: path is on mount '\\\\.\\NUL', start on mount 'F:'

scan_files() only caught OSError, so the exception escaped the ga-at-index
thread: the thread died, `ready` was never set, and @ file completion stayed
silently empty for the rest of the session.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

FRONTENDS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FRONTENDS))

import at_complete  # noqa: E402


def test_is_device_name_matches_windows_devices():
    for name in ("NUL", "nul", "Con", "AUX", "PRN", "COM1", "lpt9", "NUL.txt", "con.log"):
        assert at_complete._is_device_name(name), name
    for name in ("null.txt", "console.py", "COM10", "LPT0x", "a", "nul2"):
        assert not at_complete._is_device_name(name), name


@pytest.mark.skipif(os.name != "nt", reason="device names are Windows-only")
def test_scan_files_skips_a_real_file_named_nul(tmp_path):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    # Only the \\?\ prefix can create a real file whose name is a device name.
    with open("\\\\?\\" + str(tmp_path / "NUL"), "w", encoding="utf-8") as fh:
        fh.write("ssh-keyscan output, mis-redirected by bash\n")

    assert at_complete.scan_files(str(tmp_path)) == ["keep.txt"]


@pytest.mark.skipif(os.name != "nt", reason="device names are Windows-only")
def test_scan_files_still_lists_siblings_after_a_device_entry(tmp_path):
    names = ["a.txt", "b.py", "c.log"]
    for name in names:
        (tmp_path / name).write_text("x", encoding="utf-8")
    with open("\\\\?\\" + str(tmp_path / "CON"), "w", encoding="utf-8") as fh:
        fh.write("x")

    assert sorted(at_complete.scan_files(str(tmp_path))) == sorted(names)


def test_warm_sets_ready_even_if_scan_raises(tmp_path, monkeypatch):
    def boom(root, max_files=at_complete._MAX_FILES):
        raise RuntimeError("scandir blew up")

    monkeypatch.setattr(at_complete, "scan_files", boom)
    index = at_complete.FileIndexCache(str(tmp_path))
    index.warm()

    assert index.ready.wait(10), "ga-at-index thread died without setting ready"
    assert index.snapshot() == []
