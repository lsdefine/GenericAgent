"""Regression tests for OpenAI tool schema normalization."""
import ast
import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
_SOURCE = (ROOT / "llmcore.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)
_FUNCTION = next(
    node
    for node in _TREE.body
    if isinstance(node, ast.FunctionDef) and node.name == "_prepare_oai_tools"
)
_NAMESPACE = {"copy": copy}
exec(
    compile(ast.Module(body=[_FUNCTION], type_ignores=[]), "llmcore.py", "exec"),
    _NAMESPACE,
)
_prepare_oai_tools = _NAMESPACE["_prepare_oai_tools"]


def _builtin_tools():
    return json.loads((ROOT / "assets" / "tools_schema.json").read_text(encoding="utf-8"))


def test_missing_required_is_normalized_for_both_openai_api_modes_without_mutation():
    tools = _builtin_tools()
    original = copy.deepcopy(tools)

    for api_mode in ("chat_completions", "responses"):
        prepared = _prepare_oai_tools(tools, api_mode)
        functions = [
            tool["function"] if api_mode == "chat_completions" else tool
            for tool in prepared
        ]
        assert all(fn["parameters"]["required"] == [] for fn in functions)

    assert tools == original
    assert all("required" not in tool["function"]["parameters"] for tool in tools)


def test_existing_required_fields_are_preserved_and_schema_is_not_mutated():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]
    original = copy.deepcopy(tools)

    prepared = _prepare_oai_tools(tools)

    assert prepared[0]["function"]["parameters"]["required"] == ["query"]
    assert tools == original


def test_non_list_required_field_is_normalized_to_empty_list():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {"type": "object", "required": None},
            },
        }
    ]

    prepared = _prepare_oai_tools(tools)

    assert prepared[0]["function"]["parameters"]["required"] == []
