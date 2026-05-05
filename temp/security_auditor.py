#!/usr/bin/env python3
"""Security Auditor - Static code analysis for common Python vulnerabilities"""
import os
import re
import ast
from typing import List, Dict
from datetime import datetime

class SecurityRule:
    def __init__(self, rule_id, name, pattern, severity, description):
        self.rule_id = rule_id
        self.name = name
        self.pattern = pattern
        self.severity = severity
        self.description = description

class SecurityAuditor:
    def __init__(self):
        self.rules = [
            SecurityRule("SEC001", "Hardcoded Password", r'password\s*=\s*["\x27][^\x27"]+["\x27]', "HIGH", "Hardcoded password detected"),
            SecurityRule("SEC002", "Hardcoded Secret/API Key", r'(secret|api_key|token)\s*=\s*["\x27][^\x27"]+["\x27]', "HIGH", "Hardcoded secret or API key"),
            SecurityRule("SEC003", "SQL Injection Risk", r'execute\s*\(.*%|cursor\.execute\s*\(\s*f["\x27]', "CRITICAL", "Potential SQL injection"),
            SecurityRule("SEC004", "Unsafe Deserialization", r'pickle\.loads?\s*\(|yaml\.load\s*\([^,)]*\)', "HIGH", "Unsafe deserialization"),
            SecurityRule("SEC005", "Command Injection", r'os\.system\s*\(|subprocess\..*shell\s*=\s*True', "CRITICAL", "Potential command injection"),
            SecurityRule("SEC006", "Eval/Exec Usage", r'\beval\s*\(|\bexec\s*\(', "CRITICAL", "Use of eval/exec"),
            SecurityRule("SEC007", "Assert in Production", r'^\s*assert\s+', "LOW", "Assert stripped in optimized mode"),
            SecurityRule("SEC008", "Insecure Hash", r'hashlib\.md5\s*\(|hashlib\.sha1\s*\(', "MEDIUM", "Weak hash algorithm"),
            SecurityRule("SEC009", "Temp File Race", r'tempfile\.mktemp\s*\(', "MEDIUM", "Insecure temp file"),
            SecurityRule("SEC010", "Broad Except", r'except\s*:', "LOW", "Bare except clause"),
        ]
        self.findings = []

    def audit_file(self, filepath):
        findings = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return findings
        for i, line in enumerate(lines, 1):
            for rule in self.rules:
                if re.search(rule.pattern, line):
                    findings.append({
                        "file": filepath, "line": i, "rule_id": rule.rule_id,
                        "name": rule.name, "severity": rule.severity,
                        "description": rule.description, "code": line.strip()
                    })
        return findings

    def audit_directory(self, directory):
        all_findings = []
        for root, _, files in os.walk(directory):
            for fname in files:
                if fname.endswith(".py") and not fname.startswith("__"):
                    fpath = os.path.join(root, fname)
                    all_findings.extend(self.audit_file(fpath))
        return all_findings

    def generate_report(self, findings=None):
        findings = findings or self.findings
        self.findings = findings
        by_sev = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for f in findings:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        lines = ["# Security Audit Report",
                 f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                 "", "## Summary", f"**Total Issues:** {len(findings)}",
                 f"- CRITICAL: {by_sev['CRITICAL']}", f"- HIGH: {by_sev['HIGH']}",
                 f"- MEDIUM: {by_sev['MEDIUM']}", f"- LOW: {by_sev['LOW']}",
                 "", "## Findings"]
        for f in sorted(findings, key=lambda x: {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3}[x["severity"]]):
            lines.append(f"- **[{f['severity']}]** {f['rule_id']} {f['name']} in `{f['file']}:{f['line']}`")
            lines.append(f"  - {f['description']}")
        report = "\n".join(lines)
        filename = f"security_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(filename, "w") as f:
            f.write(report)
        return filename

if __name__ == "__main__":
    auditor = SecurityAuditor()
    test_code = '''
import os, pickle, hashlib

password = "super_secret_123"
api_key = "sk-12345"

def process(data):
    result = eval(data)
    os.system("echo " + data)
    pickle.loads(data)
    hashlib.md5(data.encode())
    try:
        x = 1/0
    except:
        pass
'''
    with open("test_vuln.py", "w") as f:
        f.write(test_code)
    findings = auditor.audit_file("test_vuln.py")
    report = auditor.generate_report(findings)
    print(f"Report: {report}")
    print(f"Found {len(findings)} issues")
    for f in findings[:5]:
        print(f"  [{f['severity']}] {f['rule_id']}: {f['name']} (line {f['line']})")
    os.remove("test_vuln.py")
    for fn in os.listdir("."):
        if fn.startswith("security_report_"):
            os.remove(fn)
    print("Security auditor ready.")
