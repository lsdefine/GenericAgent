#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GenericAgent 内置健康检查工具 (health check)
基于 oh-my-agent-check 审计理念适配

用法:
    python3 memory/agent_health_check.py [--target-dir DIR] [--json] [--mode MODE]
    
模式:
    full        全量审计 (默认)
    wrapper     仅审计 wrapper 层
    memory      仅审计记忆/上下文层
    tools       仅审计工具层
    rendering   仅审计渲染/传输层
"""

import os, sys, json, re, time
from pathlib import Path
from datetime import datetime

# ============================================================
# Configuration
# ============================================================
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# ============================================================
# Audit Engine
# ============================================================
class AgentHealthChecker:
    """Agent system health auditor — evidence-first, JSON-only internal."""

    def __init__(self, target_dir, mode="full"):
        self.target_dir = os.path.abspath(target_dir)
        self.mode = mode
        self.findings = []
        self.evidence = []
        self.conflicts = []
        self.start_time = time.time()

    def audit(self):
        """Run full audit based on mode selection."""
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

        self._calculate_duration()
        return self._build_report()

    def _layers_for_mode(self):
        layer_map = {
            "full":      ["system_prompt", "config", "memory", "tools", "agent_loop", "context_dup", "rendering", "hidden_agent"],
            "wrapper":   ["system_prompt", "config", "agent_loop", "hidden_agent"],
            "memory":    ["memory", "context_dup"],
            "tools":     ["tools", "config"],
            "rendering": ["rendering", "system_prompt"],
        }
        return layer_map.get(self.mode, layer_map["full"])

    # --------------------------------------------------------
    # Check: System Prompt
    # --------------------------------------------------------
    def _check_system_prompt(self):
        """Check for prompt conflicts, redundant instructions, missing guardrails."""
        prompt_files = [
            os.path.join(self.target_dir, "assets", "sys_prompt.txt"),
            os.path.join(self.target_dir, "assets", "sys_prompt_en.txt"),
        ]
        
        for pf in prompt_files:
            if not os.path.exists(pf):
                continue
            
            content = open(pf, "r", encoding="utf-8").read()
            lines = content.strip().split("\n")
            
            # Check 1: Excessive length (>50 lines = likely context bloat)
            if len(lines) > 50:
                self._add_finding(
                    severity=SEVERITY_MEDIUM,
                    layer="system_prompt",
                    title=f"System prompt may be too large ({len(lines)} lines in {os.path.basename(pf)})",
                    mechanism="Large system prompts dilute attention and increase instruction conflicts",
                    evidence=f"File: {pf}, {len(lines)} lines",
                    fix="Split into base prompt + modular injected sections via memory layers"
                )
            
            # Check 2: Contradictory instructions
            contradictions = self._find_prompt_contradictions(content)
            for c in contradictions:
                self._add_finding(
                    severity=SEVERITY_HIGH,
                    layer="system_prompt",
                    title=f"Contradictory instruction in {os.path.basename(pf)}",
                    mechanism=c["desc"],
                    evidence=f"Lines around: {c['line']}",
                    fix="Remove or resolve the contradiction"
                )
            
            # Check 3: Tool enforcement in prompt only (not in code)
            if "必须" in content or "must" in content.lower():
                if "tool" in content.lower() or "工具" in content:
                    self._add_finding(
                        severity=SEVERITY_MEDIUM,
                        layer="system_prompt",
                        title="Tool enforcement relies on prompt text, not code gate",
                        mechanism="Instructions in system prompt can be overridden by model; hard gates in code are stronger",
                        evidence=f"File: {pf}, contains tool-related must/must-not language",
                        fix="Move critical tool requirements to code-level validation in agent_loop.py"
                    )

    def _find_prompt_contradictions(self, content):
        """Find contradictory instructions in prompt."""
        contradictions = []
        lines = content.split("\n")
        
        # Pattern: "do X" vs "don't do X" or "always" vs "never"
        for i, line in enumerate(lines):
            lower = line.lower()
            if ("必须" in lower or "always" in lower) and i > 0:
                for j in range(max(0, i-5), i):
                    other = lines[j].lower()
                    if ("不要" in other or "不要" in line or "never" in other or "don't" in lower):
                        contradictions.append({"line": i+1, "desc": f"Line {i+1} says 'must/always' but line {j+1} says 'don't/never'"})
            if ("允许" in lower and "不允许" in lower):
                contradictions.append({"line": i+1, "desc": f"Line {i+1} contains both 'allow' and 'not allow'"})
        
        return contradictions

    # --------------------------------------------------------
    # Check: Config
    # --------------------------------------------------------
    def _check_config(self):
        """Check mykey.py and configuration for anti-patterns."""
        key_path = os.path.join(self.target_dir, "mykey.py")
        if not os.path.exists(key_path):
            # Check template
            tmpl_path = os.path.join(self.target_dir, "mykey_template.py")
            if os.path.exists(tmpl_path):
                self._add_finding(
                    severity=SEVERITY_LOW,
                    layer="config",
                    title="mykey.py not created from template",
                    mechanism="Agent cannot start without API key configuration",
                    evidence=f"Template exists: {tmpl_path}, but mykey.py missing",
                    fix="cp mykey_template.py mykey.py and fill in API keys"
                )
            return
        
        content = open(key_path, "r", encoding="utf-8").read()
        
        # Check: Hardcoded secrets
        secret_patterns = ["sk-", "ghp_", "token =", "password =", "secret ="]
        for pat in secret_patterns:
            if pat in content.lower():
                self._add_finding(
                    severity=SEVERITY_CRITICAL,
                    layer="config",
                    title="Potential hardcoded secret in mykey.py",
                    mechanism="Secrets in source code can leak via logs, git, or agent output",
                    evidence=f"Pattern '{pat}' found in {key_path}",
                    fix="Use environment variables or external keychain for secrets"
                )
        
        # Check: Multiple LLM providers without fallback logic
        if content.count("base_url") > 1 and "fallback" not in content.lower():
            self._add_finding(
                severity=SEVERITY_MEDIUM,
                layer="config",
                title="Multiple LLM providers configured without explicit fallback",
                mechanism="Without fallback logic, agent may fail silently when primary provider is down",
                evidence=f"Multiple base_url entries in {key_path}",
                fix="Add fallback provider logic or explicit provider priority in config"
            )

    # --------------------------------------------------------
    # Check: Memory Layer
    # --------------------------------------------------------
    def _check_memory_layer(self):
        """Check memory files for contamination, bloat, stale data."""
        mem_dir = os.path.join(self.target_dir, "memory")
        if not os.path.exists(mem_dir):
            return
        
        # Check L1 insight index size
        insight_path = os.path.join(mem_dir, "global_mem_insight.txt")
        if os.path.exists(insight_path):
            content = open(insight_path, "r", encoding="utf-8").read()
            lines = [l for l in content.strip().split("\n") if l.strip()]
            if len(lines) > 30:
                self._add_finding(
                    severity=SEVERITY_HIGH,
                    layer="memory",
                    title=f"L1 insight index exceeds 30-line limit ({len(lines)} lines)",
                    mechanism="Oversized L1 floods system prompt context, diluting attention for critical instructions",
                    evidence=f"File: {insight_path}, {len(lines)} lines (limit: 30)",
                    fix="Run memory compression; move detailed entries to L3 SOP files"
                )
        
        # Check L4 raw session accumulation
        l4_dir = os.path.join(mem_dir, "L4_raw_sessions")
        if os.path.exists(l4_dir):
            total_size = 0
            file_count = 0
            for root, dirs, files in os.walk(l4_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    total_size += os.path.getsize(fp)
                    file_count += 1
            
            if total_size > 10 * 1024 * 1024:  # 10MB
                self._add_finding(
                    severity=SEVERITY_MEDIUM,
                    layer="memory",
                    title=f"L4 raw sessions accumulating ({total_size / 1024 / 1024:.1f}MB, {file_count} files)",
                    mechanism="Raw session files grow unbounded; waste context tokens and disk without compression",
                    evidence=f"Directory: {l4_dir}, {file_count} files, {total_size / 1024 / 1024:.1f}MB",
                    fix="Run compress_session.py to archive and compress old sessions"
                )
        
        # Check for duplicate content across memory files
        mem_files = []
        for f in os.listdir(mem_dir):
            fp = os.path.join(mem_dir, f)
            if os.path.isfile(fp) and f.endswith((".txt", ".md")):
                try:
                    mem_files.append((f, open(fp, "r", encoding="utf-8").read()))
                except:
                    pass
        
        for i in range(len(mem_files)):
            for j in range(i+1, len(mem_files)):
                name_a, content_a = mem_files[i]
                name_b, content_b = mem_files[j]
                # Simple overlap check: shared lines > 30 chars
                shared = self._find_shared_blocks(content_a, content_b)
                if shared:
                    self._add_finding(
                        severity=SEVERITY_MEDIUM,
                        layer="memory",
                        title=f"Duplicate content between {name_a} and {name_b}",
                        mechanism="Same information in multiple memory files wastes tokens when both are loaded",
                        evidence=f"Shared blocks: {', '.join(shared[:3])}",
                        fix="Deduplicate: keep info in one file, reference from the other"
                    )

    def _find_shared_blocks(self, a, b, min_len=40):
        """Find shared text blocks between two strings."""
        shared = []
        a_lines = a.split("\n")
        b_lines = b.split("\n")
        for la in a_lines:
            la = la.strip()
            if len(la) < min_len:
                continue
            for lb in b_lines:
                lb = lb.strip()
                if la == lb and len(la) >= min_len:
                    shared.append(la[:60])
                    break
        return list(set(shared))[:5]

    # --------------------------------------------------------
    # Check: Tools Layer
    # --------------------------------------------------------
    def _check_tools_layer(self):
        """Check tool schema and implementation for gaps."""
        schema_path = os.path.join(self.target_dir, "assets", "tools_schema.json")
        if not os.path.exists(schema_path):
            return
        
        try:
            schema = json.load(open(schema_path, "r", encoding="utf-8"))
        except:
            self._add_finding(
                severity=SEVERITY_CRITICAL,
                layer="tools",
                title="tools_schema.json is invalid JSON",
                mechanism="Agent cannot register tools if schema is malformed",
                evidence=f"File: {schema_path}",
                fix="Validate and fix JSON syntax in tools_schema.json"
            )
            return
        
        tool_names = [t["function"]["name"] for t in schema]
        
        # Check: No ask_user tool = agent can't pause for human input
        if "ask_user" not in tool_names:
            self._add_finding(
                severity=SEVERITY_HIGH,
                layer="tools",
                title="No ask_user tool available",
                mechanism="Agent cannot pause for human clarification, leading to silent wrong-path execution",
                evidence=f"Tools: {tool_names}",
                fix="Add ask_user tool to tools_schema.json and implement in ga.py"
            )
        
        # Check: code_run without timeout = potential runaway process
        for t in schema:
            if t["function"]["name"] == "code_run":
                props = t["function"]["parameters"]["properties"]
                if "timeout" not in props:
                    self._add_finding(
                        severity=SEVERITY_HIGH,
                        layer="tools",
                        title="code_run has no timeout in schema",
                        mechanism="Runaway code can block agent indefinitely",
                        evidence="tools_schema.json: code_run missing timeout property",
                        fix="Add timeout property with default 60s to code_run schema"
                    )
        
        # Check: ga.py implements all declared tools
        ga_path = os.path.join(self.target_dir, "ga.py")
        if os.path.exists(ga_path):
            ga_content = open(ga_path, "r", encoding="utf-8").read()
            for name in tool_names:
                if f"do_{name}" not in ga_content:
                    self._add_finding(
                        severity=SEVERITY_HIGH,
                        layer="tools",
                        title=f"Tool '{name}' declared in schema but no do_{name} in ga.py",
                        mechanism="Agent will return 'unknown tool' error when model tries to call it",
                        evidence=f"Schema declares '{name}', ga.py missing do_{name} method",
                        fix=f"Implement do_{name} in GenericAgentHandler class"
                    )

    # --------------------------------------------------------
    # Check: Agent Loop
    # --------------------------------------------------------
    def _check_agent_loop(self):
        """Check agent_loop.py for hidden repair loops, lack of failure handling."""
        loop_path = os.path.join(self.target_dir, "agent_loop.py")
        if not os.path.exists(loop_path):
            return
        
        content = open(loop_path, "r", encoding="utf-8").read()
        lines = content.split("\n")
        
        # Check: No explicit error budget / retry limit
        retry_patterns = re.findall(r"retry|重试|repeat.*loop", content, re.IGNORECASE)
        if len(retry_patterns) > 3:
            self._add_finding(
                severity=SEVERITY_MEDIUM,
                layer="agent_loop",
                title=f"Multiple retry/repeat patterns detected ({len(retry_patterns)} occurrences)",
                mechanism="Unbounded retry loops can cause infinite recursion or token waste",
                evidence=f"File: agent_loop.py, retry-related patterns: {', '.join(retry_patterns[:5])}",
                fix="Add explicit retry limit (e.g., max 3) with circuit breaker"
            )
        
        # Check: No turn limit
        if "max_turn" not in content.lower() and "max_step" not in content.lower():
            self._add_finding(
                severity=SEVERITY_MEDIUM,
                layer="agent_loop",
                title="No explicit max turn limit in agent loop",
                mechanism="Without turn limits, agent can loop indefinitely on hard tasks, burning tokens",
                evidence="agent_loop.py: no max_turn or max_step guard found",
                fix="Add configurable max_turn limit in agent_loop or agentmain.py"
            )

    # --------------------------------------------------------
    # Check: Context Duplication
    # --------------------------------------------------------
    def _check_context_dup(self):
        """Check if same info is injected through multiple layers."""
        # Check if system prompt contains info that's also in memory
        prompt_path = os.path.join(self.target_dir, "assets", "sys_prompt.txt")
        insight_path = os.path.join(self.target_dir, "memory", "global_mem_insight.txt")
        
        if os.path.exists(prompt_path) and os.path.exists(insight_path):
            prompt = open(prompt_path, "r", encoding="utf-8").read()
            insight = open(insight_path, "r", encoding="utf-8").read()
            
            shared = self._find_shared_blocks(prompt, insight, min_len=30)
            if shared:
                self._add_finding(
                    severity=SEVERITY_MEDIUM,
                    layer="context_dup",
                    title="Duplicate content between system prompt and L1 insight index",
                    mechanism="Same info injected via system prompt AND memory index wastes context tokens",
                    evidence=f"Shared lines: {shared[:3]}",
                    fix="Keep info in ONE layer only: facts in memory, rules in system prompt"
                )

    # --------------------------------------------------------
    # Check: Rendering/Transport
    # --------------------------------------------------------
    def _check_rendering_layer(self):
        """Check for rendering mutations, transport-layer corruption."""
        launch_path = os.path.join(self.target_dir, "launch.pyw")
        if not os.path.exists(launch_path):
            return
        
        content = open(launch_path, "r", encoding="utf-8").read()
        
        # Check: JS injection that could mutate agent output
        if "inject" in content.lower():
            self._add_finding(
                severity=SEVERITY_LOW,
                layer="rendering",
                title="launch.pyw contains JS injection (inject function)",
                mechanism="JS injection in UI layer could mutate agent display without changing actual agent output",
                evidence="launch.pyw: inject() function found",
                fix="Ensure JS injection is read-only (display only), not mutating agent response data"
            )

    # --------------------------------------------------------
    # Check: Hidden Agent Layers
    # --------------------------------------------------------
    def _check_hidden_agents(self):
        """Check for implicit repair/retry/recap agents."""
        frontends_dir = os.path.join(self.target_dir, "frontends")
        if not os.path.exists(frontends_dir):
            return
        
        # Check idle_monitor in launch.pyw — it auto-injects tasks
        launch_path = os.path.join(self.target_dir, "launch.pyw")
        if os.path.exists(launch_path):
            content = open(launch_path, "r", encoding="utf-8").read()
            if "idle_monitor" in content and "inject" in content:
                self._add_finding(
                    severity=SEVERITY_LOW,
                    layer="hidden_agent",
                    title="Idle monitor auto-injects tasks after 30min inactivity",
                    mechanism="Background auto-injection acts like a hidden agent triggering work without user request",
                    evidence="launch.pyw: idle_monitor + inject functions",
                    fix="Document this behavior clearly; consider making it configurable"
                )
        
        # Check frontends for hidden LLM calls
        for f in os.listdir(frontends_dir):
            if f.endswith(".py"):
                fp = os.path.join(frontends_dir, f)
                try:
                    fc = open(fp, "r", encoding="utf-8").read()
                    if "llm" in fc.lower() and "call" in fc.lower():
                        self._add_finding(
                            severity=SEVERITY_MEDIUM,
                            layer="hidden_agent",
                            title=f"Frontend {f} may contain direct LLM calls outside main agent loop",
                            mechanism="LLM calls in frontend bypass the main agent's tool discipline and memory system",
                            evidence=f"File: frontends/{f}, contains llm+call patterns",
                            fix="Route all LLM calls through the main agent_loop for consistent control"
                        )
                except:
                    pass

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------
    def _add_finding(self, severity, layer, title, mechanism, evidence, fix):
        self.findings.append({
            "severity": severity,
            "layer": layer,
            "title": title,
            "mechanism": mechanism,
            "evidence": evidence,
            "fix": fix,
        })

    def _calculate_duration(self):
        self.duration_ms = int((time.time() - self.start_time) * 1000)

    def _build_report(self):
        severity_order = {SEVERITY_CRITICAL: 0, SEVERITY_HIGH: 1, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 3}
        sorted_findings = sorted(self.findings, key=lambda f: severity_order.get(f["severity"], 99))
        
        critical_count = sum(1 for f in sorted_findings if f["severity"] == SEVERITY_CRITICAL)
        high_count = sum(1 for f in sorted_findings if f["severity"] == SEVERITY_HIGH)
        
        if critical_count > 0:
            verdict = "UNHEALTHY — Critical issues found"
        elif high_count > 2:
            verdict = "DEGRADED — Multiple high-severity issues"
        elif high_count > 0:
            verdict = "CAUTION — High-severity issues present"
        else:
            verdict = "MOSTLY HEALTHY — Minor issues only"
        
        return {
            "verdict": verdict,
            "target": self.target_dir,
            "mode": self.mode,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": self.duration_ms,
            "summary": {
                "total": len(sorted_findings),
                "critical": critical_count,
                "high": high_count,
                "medium": sum(1 for f in sorted_findings if f["severity"] == SEVERITY_MEDIUM),
                "low": sum(1 for f in sorted_findings if f["severity"] == SEVERITY_LOW),
            },
            "findings": sorted_findings,
        }


# ============================================================
# CLI Entry Point
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="GenericAgent Health Check — evidence-first agent audit")
    parser.add_argument("--target-dir", default=None, help="Target GenericAgent project directory")
    parser.add_argument("--json", action="store_true", help="Output raw JSON report")
    parser.add_argument("--mode", choices=["full", "wrapper", "memory", "tools", "rendering"], default="full")
    args = parser.parse_args()

    target = args.target_dir or os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(target):
        print(f"[Error] Target directory not found: {target}")
        sys.exit(1)

    print(f"[*] GenericAgent Health Check — Mode: {args.mode}")
    print(f"[*] Target: {target}")
    print()

    checker = AgentHealthChecker(target, mode=args.mode)
    report = checker.audit()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    # Human-readable output
    s = report["summary"]
    print(f"{'='*60}")
    print(f"  Verdict: {report['verdict']}")
    print(f"  Total: {s['total']} findings ({s['critical']}C / {s['high']}H / {s['medium']}M / {s['low']}L)")
    print(f"  Duration: {report['duration_ms']}ms")
    print(f"{'='*60}")
    print()

    for i, f in enumerate(report["findings"], 1):
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(f["severity"], "⚪")
        print(f"{i}. {icon} [{f['severity'].upper()}] {f['title']}")
        print(f"   Layer: {f['layer']}")
        print(f"   Why: {f['mechanism']}")
        print(f"   Evidence: {f['evidence']}")
        print(f"   Fix: {f['fix']}")
        print()

    print(f"{'='*60}")
    print(f"  Total: {s['total']} findings")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
