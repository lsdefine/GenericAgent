"""Contracts for the package-owned bridge/conductor plus external GA_ROOT architecture."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
BRIDGE_SOURCE = (ROOT / "frontends" / "desktop_bridge.py").read_text(encoding="utf-8")
CONDUCTOR_SOURCE = (ROOT / "frontends" / "conductor.py").read_text(encoding="utf-8")
HUB_SOURCE = (ROOT / "frontends" / "hub.py").read_text(encoding="utf-8")
PROBE = ROOT / "frontends" / "ga_contract_probe.py"


def _load_function(source: str, name: str, namespace: dict):
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "contract.py", "exec"), namespace)
    return namespace[name]


def test_conductor_prefers_a_valid_external_ga_root(tmp_path, monkeypatch):
    external = tmp_path / "external"
    external.mkdir()
    (external / "agentmain.py").write_text("# core\n", encoding="utf-8")
    monkeypatch.setenv("GA_ROOT", str(external))
    resolve = _load_function(CONDUCTOR_SOURCE, "_resolve_ga_root", {"os": os})

    assert resolve() == str(external.resolve())


def test_bridge_discovers_package_conductor_but_external_scheduler(tmp_path):
    external = tmp_path / "external"
    (external / "reflect").mkdir(parents=True)
    (external / "reflect" / "scheduler.py").write_text("# scheduler\n", encoding="utf-8")
    bundle_frontends = tmp_path / "bundle" / "frontends"
    bundle_frontends.mkdir(parents=True)
    bundled_conductor = bundle_frontends / "conductor.py"
    bundled_conductor.write_text("# conductor\n", encoding="utf-8")
    discover = _load_function(
        BRIDGE_SOURCE,
        "discover_extra_services",
        {"Path": Path, "List": list, "APP_DIR": bundle_frontends, "sys": sys},
    )

    catalog = {item["id"]: item for item in discover(external)}

    assert catalog["frontends/conductor.py"]["cmd"][1] == str(bundled_conductor)
    assert catalog["reflect/scheduler.py"]["cmd"][-1] == "reflect/scheduler.py"


def test_service_spawn_injects_effective_ga_root():
    tree = ast.parse(BRIDGE_SOURCE)
    service_manager = next(
        item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "ServiceManager"
    )
    start_service = next(
        item for item in service_manager.body
        if isinstance(item, ast.FunctionDef) and item.name == "start_service"
    )
    string_constants = {
        node.value for node in ast.walk(start_service)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "GA_ROOT" in string_constants


def test_missing_optional_p2p_dependencies_cannot_abort_hub_setup():
    tree = ast.parse(HUB_SOURCE)
    p2p_import = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "hub_p2p"
    )
    guard = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Try) and p2p_import in set(ast.walk(node))
    )

    assert any(
        handler.type is None
        or (isinstance(handler.type, ast.Name) and handler.type.id == "Exception")
        for handler in guard.handlers
    )


def _run_probe(core: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    completed = subprocess.run(
        [sys.executable, str(PROBE), str(core)],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed, json.loads(completed.stdout.strip().splitlines()[-1])


def test_compatibility_probe_rejects_a_core_missing_generic_agent(tmp_path):
    (tmp_path / "agentmain.py").write_text("# no GenericAgent\n", encoding="utf-8")
    (tmp_path / "llmcore.py").write_text(
        "def reload_mykeys(): pass\ndef _record_usage(usage, api_mode): pass\n",
        encoding="utf-8",
    )

    completed, verdict = _run_probe(tmp_path)

    assert completed.returncode == 1
    assert verdict == {"ok": False, "missing": ["agentmain.GenericAgent"], "error": ""}


def test_compatibility_probe_accepts_the_desktop_core_contract(tmp_path):
    (tmp_path / "agentmain.py").write_text(
        """class GenericAgent:
    def run(self): pass
    def put_task(self, prompt, images=None, source=None): pass
    def next_llm(self): pass
    def load_llm_sessions(self): pass
    def get_llm_name(self, model=None): pass
    def abort(self): pass
""",
        encoding="utf-8",
    )
    (tmp_path / "llmcore.py").write_text(
        "def reload_mykeys(): pass\ndef _record_usage(usage, api_mode): pass\n",
        encoding="utf-8",
    )

    completed, verdict = _run_probe(tmp_path)

    assert completed.returncode == 0
    assert verdict == {"ok": True, "missing": [], "error": ""}
