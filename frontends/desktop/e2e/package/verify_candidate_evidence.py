#!/usr/bin/env python3
"""Combine three real-package reports and enforce the P2 candidate evidence gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


COMMON_CHECKS = (
    "packageShape",
    "deterministicChat",
    "uploadUnderExternalRoot",
    "memoryImport",
    "warmRestart",
    "foreignListenerSurvived",
    "portRecovery",
    "relocation",
    "staleOverrideFallback",
    "optionalP2PDoesNotBlockReady",
    "settingsRestored",
    "finalPortFree",
    "finalOwnedProcessesExited",
)


def load(path: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read {target}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"report is not an object: {target}")
    value["_path"] = str(target)
    return value


def assert_report(name: str, report: dict[str, Any], expected_commit: str) -> list[str]:
    failures: list[str] = []
    actual_commit = str(report.get("expectedCommit", "")).lower()
    if actual_commit != expected_commit.lower():
        failures.append(f"{name}: commit {actual_commit!r} != {expected_commit!r}")
    if report.get("releaseVersion") != "0.2.0":
        failures.append(f"{name}: release version is not 0.2.0")
    if report.get("success") is not True:
        failures.append(f"{name}: automated journey did not pass")
    if not str(report.get("artifact", {}).get("sha256", "")):
        failures.append(f"{name}: artifact SHA-256 is missing")
    checks = report.get("checks", {})
    for check in COMMON_CHECKS:
        if not checks.get(check):
            failures.append(f"{name}: required check {check} did not pass")
    if name == "macos" and checks.get("macAppImmutable") is not True:
        failures.append("macos: signed .app immutability did not pass")
    required_bootstrap = {"first-launch", "warm-restart", "foreign-port", "after-port-release", "relocated", "stale-override"}
    missing_bootstrap = sorted(required_bootstrap - set(report.get("bootstrap", {})))
    if missing_bootstrap:
        failures.append(f"{name}: missing bootstrap evidence {missing_bootstrap}")
    pending = [key for key, value in report.get("manualChecklist", {}).items() if value != "pass"]
    if pending:
        failures.append(f"{name}: manual checklist is incomplete: {pending}")
    if len(report.get("screenshots", [])) < 2 and name != "windows":
        failures.append(f"{name}: fewer than two screenshots were recorded")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--windows", required=True)
    parser.add_argument("--linux", required=True)
    parser.add_argument("--macos", required=True)
    parser.add_argument("--windows-native-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    reports = {
        "windows": load(args.windows),
        "linux": load(args.linux),
        "macos": load(args.macos),
    }
    failures: list[str] = []
    for name, report in reports.items():
        failures.extend(assert_report(name, report, args.expected_commit))

    windows_native = load(args.windows_native_report)
    if windows_native.get("success") is not True:
        failures.append("windows native wrapper did not pass")
    if windows_native.get("checks", {}).get("portConflictRecovery") is not True:
        failures.append("windows native retry path did not pass")
    if windows_native.get("checks", {}).get("settingsRestored") is not True:
        failures.append("windows native wrapper did not restore the original settings file")
    native_pending = [
        key for key, value in windows_native.get("manualChecklist", {}).items() if value != "pass"
    ]
    if native_pending:
        failures.append(f"windows native manual checklist is incomplete: {native_pending}")

    manifest = {
        "schemaVersion": 1,
        "candidateCommit": args.expected_commit,
        "releaseVersion": "0.2.0",
        "platforms": {
            name: {
                "report": report["_path"],
                "artifactSha256": report.get("artifact", {}).get("sha256"),
                "environment": report.get("environment"),
                "success": report.get("success"),
            }
            for name, report in reports.items()
        },
        "windowsNativeReport": windows_native["_path"],
        "gate": "pass" if not failures else "fail",
        "failures": failures,
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
