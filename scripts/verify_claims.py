#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
verify_claims.py - 通用事实验证脚本
用途: 为 Agent 提供"报告前最后验证"的统一入口
设计原则: 所有验证必须有工具输出证据, 无证据的结论自动标记为 UNVERIFIED
"""

import subprocess
import sys
import os
import json
from typing import List, Dict


class VerificationResult:
    def __init__(self, claim: str):
        self.claim = claim
        self.evidence: List[Dict] = []
        self.status: str = "UNVERIFIED"
        self.summary: str = ""

    def add_evidence(self, action: str, tool: str, output_summary: str, passed: bool):
        self.evidence.append({
            "action": action, "tool": tool,
            "output": output_summary, "passed": passed
        })

    def finalize(self):
        if not self.evidence:
            self.status = "UNVERIFIED"
            self.summary = "无任何工具证据 -> 结论无效"
        elif all(e["passed"] for e in self.evidence):
            self.status = "PASS"
            self.summary = "所有检查通过"
        else:
            self.status = "FAIL"
            failed = [e for e in self.evidence if not e["passed"]]
            self.summary = f"共{len(self.evidence)}项检查, {len(failed)}项失败"
        return self.to_markdown()

    def to_markdown(self) -> str:
        lines = [f"## 验证: {self.claim}", "",
                 f"**最终裁定: {self.status}**",
                 f"**摘要:** {self.summary}", "",
                 "| # | 验证动作 | 工具 | 关键输出 | PASS/FAIL |",
                 "|---|---------|------|---------|:--------:|"]
        for i, e in enumerate(self.evidence, 1):
            ps = "PASS" if e["passed"] else "FAIL"
            lines.append(f"| {i} | {e['action']} | {e['tool']} | {e['output']} | {ps} |")
        lines.append("")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({
            "claim": self.claim, "status": self.status,
            "summary": self.summary, "evidence": self.evidence
        }, ensure_ascii=False, indent=2)


def verify_claim(claim: str, evidence_builder=None) -> VerificationResult:
    vr = VerificationResult(claim)
    if evidence_builder:
        evidence_builder(vr)
    vr.finalize()
    return vr


def run_command_verification(claim: str, command: str, success_keywords: list = None) -> VerificationResult:
    vr = VerificationResult(claim)
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = (result.stdout + "\n" + result.stderr).strip()
        exit_ok = result.returncode == 0
        kw_ok = True
        missing_kw = []
        if success_keywords:
            for kw in success_keywords:
                if kw.lower() not in output.lower():
                    kw_ok = False
                    missing_kw.append(kw)
        passed = exit_ok and kw_ok
        summary = output[:200].replace("\n", " | ")
        if not exit_ok:
            summary += f" [exit={result.returncode}]"
        if missing_kw:
            summary += f" [缺失关键词: {missing_kw}]"
        vr.add_evidence(f"run: {command[:80]}", "code_run", summary, passed)
    except Exception as e:
        vr.add_evidence(f"run: {command[:80]}", "code_run", f"异常: {str(e)[:100]}", False)
    vr.finalize()
    return vr


def verify_file_content(claim: str, file_path: str, expected_content: str = None) -> VerificationResult:
    vr = VerificationResult(claim)
    if not os.path.exists(file_path):
        vr.add_evidence(f"检查文件存在: {file_path}", "file_read", "文件不存在", False)
        vr.finalize()
        return vr
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if expected_content:
            found = expected_content in content
            vr.add_evidence(f"检查: {file_path}", "file_read",
                            f"包含期望内容={found}", passed=found)
        else:
            vr.add_evidence(f"检查: {file_path}", "file_read",
                            f"文件存在, {len(content)} bytes", passed=True)
    except Exception as e:
        vr.add_evidence(f"读取: {file_path}", "file_read", f"失败: {str(e)[:100]}", False)
    vr.finalize()
    return vr


def main():
    import argparse
    parser = argparse.ArgumentParser(description="通用事实验证工具")
    parser.add_argument("--check", required=True, help="待验证的结论")
    parser.add_argument("--command", help="验证命令")
    parser.add_argument("--file", help="验证文件路径")
    parser.add_argument("--expect", help="文件应包含的内容")
    parser.add_argument("--keywords", nargs="*", help="命令输出应包含的关键词")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    if args.command:
        vr = run_command_verification(args.check, args.command, args.keywords)
    elif args.file:
        vr = verify_file_content(args.check, args.file, args.expect)
    else:
        print("错误: 必须指定 --command 或 --file")
        sys.exit(1)

    if args.json:
        print(vr.to_json())
    else:
        print(vr.to_markdown())
    sys.exit(0 if vr.status == "PASS" else 1)


if __name__ == "__main__":
    main()
