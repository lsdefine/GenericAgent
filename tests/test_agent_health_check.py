"""Tests for the standalone agent health check script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_health_check.py"


def _make_repo_fixture(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "memory").mkdir(parents=True)
    (root / "frontends").mkdir(parents=True)
    (root / "assets" / "sys_prompt.txt").write_text(
        "\n".join(["Always use tools."] * 55),
        encoding="utf-8",
    )
    (root / "assets" / "tools_schema.json").write_text(
        json.dumps(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "code_run",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (root / "ga.py").write_text(
        "class GenericAgentHandler:\n    def do_file_read(self):\n        return None\n",
        encoding="utf-8",
    )
    (root / "agent_loop.py").write_text(
        "def run_loop():\n    retry = 1\n    retry = retry + 1\n    retry = retry + 1\n    retry = retry + 1\n",
        encoding="utf-8",
    )
    return root


def test_health_check_script_emits_json_report(tmp_path: Path) -> None:
    target = _make_repo_fixture(tmp_path / "repo")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--target-dir", str(target), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["target"] == str(target.resolve())
    assert report["summary"]["total"] >= 1
    assert any(finding["layer"] == "tools" for finding in report["findings"])


def test_health_check_script_human_output_mentions_verdict(tmp_path: Path) -> None:
    target = _make_repo_fixture(tmp_path / "repo")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--target-dir", str(target), "--mode", "tools"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "Verdict:" in proc.stdout
    assert "code_run has no timeout in schema" in proc.stdout
