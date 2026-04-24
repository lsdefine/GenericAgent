#!/usr/bin/env python3
"""Standalone health check for a GenericAgent checkout.

This helper is intentionally standalone:
- no monkey-patching
- no tool registration
- no direct memory writes
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_ORDER = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_HIGH: 1,
    SEVERITY_MEDIUM: 2,
    SEVERITY_LOW: 3,
}


@dataclass
class Finding:
    severity: str
    layer: str
    title: str
    mechanism: str
    evidence: str
    fix: str


class AgentHealthChecker:
    """Evidence-first auditor for a GenericAgent repository."""

    def __init__(self, target_dir: str | Path, mode: str = "full") -> None:
        self.target_dir = Path(target_dir).resolve()
        self.mode = mode
        self.findings: list[Finding] = []
        self.start_time = time.time()

    def audit(self) -> dict:
        layers = self._layers_for_mode()
        if "system_prompt" in layers:
            self._check_system_prompt()
        if "config" in layers:
            self._check_config()
        if "memory" in layers:
            self._check_memory_layer()
        if "tools" in layers:
            self._check_tools_layer()
        if "agent_loop" in layers:
            self._check_agent_loop()
        if "context_dup" in layers:
            self._check_context_dup()
        if "rendering" in layers:
            self._check_rendering_layer()
        if "hidden_agent" in layers:
            self._check_hidden_agents()
        return self._build_report()

    def _layers_for_mode(self) -> list[str]:
        layer_map = {
            "full": [
                "system_prompt",
                "config",
                "memory",
                "tools",
                "agent_loop",
                "context_dup",
                "rendering",
                "hidden_agent",
            ],
            "wrapper": ["system_prompt", "config", "agent_loop", "hidden_agent"],
            "memory": ["memory", "context_dup"],
            "tools": ["tools", "config"],
            "rendering": ["rendering", "system_prompt"],
        }
        return layer_map.get(self.mode, layer_map["full"])

    def _read_text(self, *parts: str) -> str | None:
        path = self.target_dir.joinpath(*parts)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="ignore")

    def _add_finding(self, severity: str, layer: str, title: str, mechanism: str, evidence: str, fix: str) -> None:
        self.findings.append(Finding(severity, layer, title, mechanism, evidence, fix))

    def _check_system_prompt(self) -> None:
        for name in ("sys_prompt.txt", "sys_prompt_en.txt"):
            content = self._read_text("assets", name)
            if not content:
                continue

            lines = [line for line in content.splitlines() if line.strip()]
            if len(lines) > 50:
                self._add_finding(
                    SEVERITY_MEDIUM,
                    "system_prompt",
                    f"System prompt may be too large ({len(lines)} lines in {name})",
                    "Large system prompts can dilute attention and increase instruction conflicts.",
                    f"assets/{name}: {len(lines)} non-empty lines",
                    "Split stable rules from optional guidance and keep facts in memory layers.",
                )

            contradictions = self._find_prompt_contradictions(lines)
            for contradiction in contradictions:
                self._add_finding(
                    SEVERITY_HIGH,
                    "system_prompt",
                    f"Contradictory instruction in {name}",
                    contradiction,
                    f"assets/{name}",
                    "Remove or reconcile the conflicting instructions.",
                )

            lower = content.lower()
            if ("must" in lower or "必须" in content) and ("tool" in lower or "工具" in content):
                self._add_finding(
                    SEVERITY_MEDIUM,
                    "system_prompt",
                    "Tool enforcement relies on prompt text, not code gate",
                    "Prompt-only tool requirements can be bypassed more easily than code-level validation.",
                    f"assets/{name} contains tool-related must/required language",
                    "Move critical tool requirements into code-level validation or schema constraints.",
                )

    def _find_prompt_contradictions(self, lines: list[str]) -> list[str]:
        contradictions: list[str] = []
        for index, line in enumerate(lines):
            lower = line.lower()
            if "允许" in line and "不允许" in line:
                contradictions.append(f"line {index + 1} contains both allow and disallow language")
            if ("always" in lower or "必须" in line) and index > 0:
                for previous_index in range(max(0, index - 5), index):
                    previous = lines[previous_index].lower()
                    if "never" in previous or "don't" in previous or "不要" in lines[previous_index]:
                        contradictions.append(f"line {index + 1} conflicts with line {previous_index + 1}")
                        break
        return contradictions

    def _check_config(self) -> None:
        mykey_path = self.target_dir / "mykey.py"
        template_path = self.target_dir / "mykey_template.py"
        if not mykey_path.exists():
            if template_path.exists():
                self._add_finding(
                    SEVERITY_LOW,
                    "config",
                    "mykey.py not created from template",
                    "The runtime cannot start without local key configuration.",
                    "mykey_template.py exists but mykey.py is missing",
                    "Copy mykey_template.py to mykey.py and fill in the required keys.",
                )
            return

        content = mykey_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in ("sk-", "ghp_", "token =", "password =", "secret ="):
            if pattern in content.lower():
                self._add_finding(
                    SEVERITY_CRITICAL,
                    "config",
                    "Potential hardcoded secret in mykey.py",
                    "Secrets in source code can leak through logs, backups, or version control.",
                    f"Pattern '{pattern}' found in mykey.py",
                    "Move secrets into environment variables, local-only key files, or an external key store.",
                )
                break

        if content.count("base_url") > 1 and "fallback" not in content.lower():
            self._add_finding(
                SEVERITY_MEDIUM,
                "config",
                "Multiple providers configured without explicit fallback logic",
                "Multiple provider endpoints without priority/fallback logic can fail unpredictably.",
                "mykey.py contains multiple base_url entries",
                "Document or implement explicit provider selection or fallback behavior.",
            )

    def _check_memory_layer(self) -> None:
        insight_path = self.target_dir / "memory" / "global_mem_insight.txt"
        if insight_path.exists():
            lines = [line for line in insight_path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
            if len(lines) > 30:
                self._add_finding(
                    SEVERITY_HIGH,
                    "memory",
                    f"L1 insight index exceeds 30-line guideline ({len(lines)} lines)",
                    "An oversized L1 memory index can crowd out higher-signal context.",
                    f"memory/global_mem_insight.txt: {len(lines)} non-empty lines",
                    "Compress or move detailed entries into more specific SOP or archive files.",
                )

        raw_sessions = self.target_dir / "memory" / "L4_raw_sessions"
        if raw_sessions.exists():
            files = [path for path in raw_sessions.rglob("*") if path.is_file()]
            total_size = sum(path.stat().st_size for path in files)
            if total_size > 10 * 1024 * 1024:
                self._add_finding(
                    SEVERITY_MEDIUM,
                    "memory",
                    f"L4 raw sessions accumulating ({total_size / 1024 / 1024:.1f}MB)",
                    "Large raw-session archives can bloat disk usage and tempt overloading context recovery.",
                    f"memory/L4_raw_sessions: {len(files)} files, {total_size / 1024 / 1024:.1f}MB",
                    "Archive or compress old session files and keep only what is still retrieval-worthy.",
                )

        memory_dir = self.target_dir / "memory"
        if not memory_dir.exists():
            return

        text_files = []
        for path in memory_dir.iterdir():
            if path.is_file() and path.suffix in {".txt", ".md"}:
                text_files.append((path.name, path.read_text(encoding="utf-8", errors="ignore")))

        for index, (name_a, content_a) in enumerate(text_files):
            for name_b, content_b in text_files[index + 1:]:
                shared_blocks = self._find_shared_blocks(content_a, content_b, min_len=40)
                if shared_blocks:
                    self._add_finding(
                        SEVERITY_MEDIUM,
                        "memory",
                        f"Duplicate content between {name_a} and {name_b}",
                        "The same material appears in multiple memory files.",
                        f"Shared blocks: {', '.join(shared_blocks[:3])}",
                        "Keep repeated information in one place and link to it from other notes.",
                    )

    def _find_shared_blocks(self, text_a: str, text_b: str, *, min_len: int) -> list[str]:
        lines_b = {line.strip() for line in text_b.splitlines() if len(line.strip()) >= min_len}
        matches = []
        for line in text_a.splitlines():
            stripped = line.strip()
            if len(stripped) >= min_len and stripped in lines_b:
                matches.append(stripped[:60])
        return sorted(set(matches))[:5]

    def _check_tools_layer(self) -> None:
        schema_path = self.target_dir / "assets" / "tools_schema.json"
        if not schema_path.exists():
            return

        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._add_finding(
                SEVERITY_CRITICAL,
                "tools",
                "tools_schema.json is invalid JSON",
                "Malformed tool schema prevents reliable tool registration.",
                "assets/tools_schema.json could not be parsed",
                "Fix JSON syntax in assets/tools_schema.json.",
            )
            return

        tool_names = [entry["function"]["name"] for entry in schema if "function" in entry]
        if "ask_user" not in tool_names:
            self._add_finding(
                SEVERITY_HIGH,
                "tools",
                "No ask_user tool available",
                "Without a human-clarification tool, the agent must guess on ambiguous tasks.",
                f"Declared tools: {tool_names}",
                "Add or restore ask_user support in the tool schema and runtime.",
            )

        for entry in schema:
            function = entry.get("function", {})
            if function.get("name") == "code_run":
                properties = function.get("parameters", {}).get("properties", {})
                if "timeout" not in properties:
                    self._add_finding(
                        SEVERITY_HIGH,
                        "tools",
                        "code_run has no timeout in schema",
                        "Runaway code execution can block the agent indefinitely.",
                        "assets/tools_schema.json: code_run missing timeout parameter",
                        "Add a timeout parameter and enforce it in the runtime.",
                    )

        ga_path = self.target_dir / "ga.py"
        if ga_path.exists():
            ga_content = ga_path.read_text(encoding="utf-8", errors="ignore")
            for tool_name in tool_names:
                if f"do_{tool_name}" not in ga_content:
                    self._add_finding(
                        SEVERITY_HIGH,
                        "tools",
                        f"Tool '{tool_name}' declared in schema but no do_{tool_name} in ga.py",
                        "The runtime may expose a tool in schema that it cannot actually execute.",
                        f"assets/tools_schema.json declares '{tool_name}', ga.py lacks do_{tool_name}",
                        f"Implement do_{tool_name} or remove it from the schema.",
                    )

    def _check_agent_loop(self) -> None:
        content = self._read_text("agent_loop.py")
        if not content:
            return

        retry_patterns = re.findall(r"retry|重试|repeat.*loop", content, flags=re.IGNORECASE)
        if len(retry_patterns) > 3:
            self._add_finding(
                SEVERITY_MEDIUM,
                "agent_loop",
                f"Multiple retry/repeat patterns detected ({len(retry_patterns)} occurrences)",
                "Too many implicit retry patterns increase the chance of runaway loops.",
                f"agent_loop.py retry-related matches: {retry_patterns[:5]}",
                "Use explicit retry budgets or circuit breakers around recovery loops.",
            )

        lower = content.lower()
        if "max_turn" not in lower and "max_step" not in lower:
            self._add_finding(
                SEVERITY_MEDIUM,
                "agent_loop",
                "No explicit max turn limit in agent loop",
                "Without a turn limit, the agent can continue looping on hard tasks.",
                "agent_loop.py has no obvious max_turn or max_step guard",
                "Add a configurable turn or step limit for long-running loops.",
            )

    def _check_context_dup(self) -> None:
        prompt = self._read_text("assets", "sys_prompt.txt")
        insight = self._read_text("memory", "global_mem_insight.txt")
        if not prompt or not insight:
            return

        shared = self._find_shared_blocks(prompt, insight, min_len=30)
        if shared:
            self._add_finding(
                SEVERITY_MEDIUM,
                "context_dup",
                "Duplicate content between system prompt and L1 insight index",
                "The same guidance appears in multiple context layers.",
                f"Shared lines: {shared[:3]}",
                "Keep rules in the system prompt and facts/routing hints in memory, not both.",
            )

    def _check_rendering_layer(self) -> None:
        content = self._read_text("launch.pyw")
        if content and "inject" in content.lower():
            self._add_finding(
                SEVERITY_LOW,
                "rendering",
                "launch.pyw contains JS injection hooks",
                "UI-side injection can mutate what the user sees even if the core response is correct.",
                "launch.pyw contains 'inject' patterns",
                "Keep injection logic display-only and document any response-shaping behavior.",
            )

    def _check_hidden_agents(self) -> None:
        content = self._read_text("launch.pyw")
        if content and "idle_monitor" in content and "inject" in content:
            self._add_finding(
                SEVERITY_LOW,
                "hidden_agent",
                "Idle monitor auto-injects tasks after inactivity",
                "Background task injection acts like a hidden autonomous layer.",
                "launch.pyw contains idle_monitor and inject patterns",
                "Document this behavior clearly and make it easy to disable.",
            )

        frontends_dir = self.target_dir / "frontends"
        if not frontends_dir.exists():
            return

        for path in sorted(frontends_dir.glob("*.py")):
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
            if "llm" in content and "call" in content:
                self._add_finding(
                    SEVERITY_MEDIUM,
                    "hidden_agent",
                    f"Frontend {path.name} may contain direct LLM calls outside the main loop",
                    "Direct frontend-side LLM calls can bypass core memory/tool discipline.",
                    f"frontends/{path.name} contains llm + call patterns",
                    "Prefer routing LLM calls through the main agent orchestration path.",
                )

    def _build_report(self) -> dict:
        ordered = sorted(self.findings, key=lambda finding: SEVERITY_ORDER[finding.severity])
        summary = {
            "total": len(ordered),
            "critical": sum(f.severity == SEVERITY_CRITICAL for f in ordered),
            "high": sum(f.severity == SEVERITY_HIGH for f in ordered),
            "medium": sum(f.severity == SEVERITY_MEDIUM for f in ordered),
            "low": sum(f.severity == SEVERITY_LOW for f in ordered),
        }
        if summary["critical"]:
            verdict = "UNHEALTHY — Critical issues found"
        elif summary["high"] > 2:
            verdict = "DEGRADED — Multiple high-severity issues"
        elif summary["high"]:
            verdict = "CAUTION — High-severity issues present"
        else:
            verdict = "MOSTLY HEALTHY — Minor issues only"

        return {
            "verdict": verdict,
            "target": str(self.target_dir),
            "mode": self.mode,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": int((time.time() - self.start_time) * 1000),
            "summary": summary,
            "findings": [
                {
                    "severity": finding.severity,
                    "layer": finding.layer,
                    "title": finding.title,
                    "mechanism": finding.mechanism,
                    "evidence": finding.evidence,
                    "fix": finding.fix,
                }
                for finding in ordered
            ],
        }


def render_human_report(report: dict) -> str:
    lines = [
        f"GenericAgent Health Check — mode: {report['mode']}",
        f"Target: {report['target']}",
        "",
        f"Verdict: {report['verdict']}",
        "Total: {total} findings ({critical}C / {high}H / {medium}M / {low}L)".format(**report["summary"]),
        f"Duration: {report['duration_ms']}ms",
        "",
    ]
    icons = {
        SEVERITY_CRITICAL: "🔴",
        SEVERITY_HIGH: "🟠",
        SEVERITY_MEDIUM: "🟡",
        SEVERITY_LOW: "🟢",
    }
    for index, finding in enumerate(report["findings"], start=1):
        lines.extend(
            [
                f"{index}. {icons.get(finding['severity'], '⚪')} [{finding['severity'].upper()}] {finding['title']}",
                f"   Layer: {finding['layer']}",
                f"   Why: {finding['mechanism']}",
                f"   Evidence: {finding['evidence']}",
                f"   Fix: {finding['fix']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone health check for a GenericAgent checkout.")
    parser.add_argument(
        "--target-dir",
        default=None,
        help="Path to the GenericAgent repository root. Defaults to the parent of this script directory.",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "wrapper", "memory", "tools", "rendering"],
        default="full",
        help="Audit scope to run.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of the human-readable report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    target = Path(args.target_dir).resolve() if args.target_dir else Path(__file__).resolve().parents[1]
    if not target.exists():
        print(f"[Error] Target directory not found: {target}")
        return 1

    report = AgentHealthChecker(target, mode=args.mode).audit()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
