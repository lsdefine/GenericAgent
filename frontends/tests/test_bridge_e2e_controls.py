"""Security and one-shot semantics for the bridge E2E control plane."""
from __future__ import annotations

import ast
import os
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE = (ROOT / "frontends" / "desktop_bridge.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function_node(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return next(
        node
        for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _load_helpers():
    wanted = {
        "_E2E_NEXT_TURN",
        "_E2E_CONTROL_LOCK",
        "_e2e_control_token",
        "_set_e2e_next_turn",
        "_consume_e2e_next_turn",
    }
    nodes = []
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            nodes.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            if names & wanted:
                nodes.append(node)
    namespace = {"os": os, "threading": threading}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "desktop_bridge.py", "exec"), namespace)
    return namespace


def test_control_requires_explicit_e2e_flag_and_random_token(monkeypatch):
    helpers = _load_helpers()
    monkeypatch.delenv("GA_E2E", raising=False)
    monkeypatch.setenv("GA_E2E_CONTROL_TOKEN", "secret")
    assert helpers["_e2e_control_token"]() is None

    monkeypatch.setenv("GA_E2E", "1")
    monkeypatch.delenv("GA_E2E_CONTROL_TOKEN", raising=False)
    assert helpers["_e2e_control_token"]() is None

    monkeypatch.setenv("GA_E2E_CONTROL_TOKEN", "secret")
    assert helpers["_e2e_control_token"]() == "secret"


def test_next_turn_override_is_validated_and_consumed_once():
    helpers = _load_helpers()
    with pytest.raises(ValueError, match="empty"):
        helpers["_set_e2e_next_turn"]("crash")

    helpers["_set_e2e_next_turn"]("empty")
    assert helpers["_consume_e2e_next_turn"]() == "empty"
    assert helpers["_consume_e2e_next_turn"]() is None


def test_e2e_route_is_not_registered_without_the_control_gate():
    create_app = _function_node("create_app")
    registrations = [
        node
        for node in ast.walk(create_app)
        if isinstance(node, ast.Call)
        and any(
            isinstance(arg, ast.Constant) and arg.value == "/__e2e__/next-turn"
            for arg in node.args
        )
    ]
    assert len(registrations) == 1

    registration = registrations[0]
    gate = next(
        node
        for node in ast.walk(create_app)
        if isinstance(node, ast.If) and registration in list(ast.walk(node))
    )
    assert isinstance(gate.test, ast.Compare)
    assert isinstance(gate.test.left, ast.Call)
    assert isinstance(gate.test.left.func, ast.Name)
    assert gate.test.left.func.id == "_e2e_control_token"


def test_e2e_handler_requires_loopback_and_secret_header():
    handler = _function_node("e2e_next_turn_handler")
    called_names = {
        node.func.id
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    constants = {
        node.value
        for node in ast.walk(handler)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "_e2e_control_token" in called_names
    assert "_is_local_peer" in called_names
    assert "X-GA-E2E-Token" in constants
    assert any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "web"
        and node.attr == "HTTPNotFound"
        for node in ast.walk(handler)
    )
