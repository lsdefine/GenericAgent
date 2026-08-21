import importlib.util
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


journey = load_module(
    "real_package_journey",
    "frontends/desktop/e2e/package/real_package_journey.py",
)
evidence = load_module(
    "verify_candidate_evidence",
    "frontends/desktop/e2e/package/verify_candidate_evidence.py",
)


def complete_report(platform: str = "linux"):
    checks = {name: True for name in evidence.COMMON_CHECKS}
    checks["portRecovery"] = "release-then-production-restart"
    if platform == "macos":
        checks["macAppImmutable"] = True
    bootstrap = {
        name: {"phase": "failed" if name == "foreign-port" else "ready"}
        for name in (
            "first-launch",
            "warm-restart",
            "foreign-port",
            "after-port-release",
            "relocated",
            "stale-override",
        )
    }
    return {
        "expectedCommit": "abc1234",
        "releaseVersion": "0.2.0",
        "artifact": {"sha256": "f" * 64},
        "success": True,
        "checks": checks,
        "bootstrap": bootstrap,
        "manualChecklist": {"nativeVisuals": "pass"},
        "screenshots": ["ready.png", "foreign.png"],
    }


def test_candidate_report_contract_accepts_complete_platform_evidence():
    assert evidence.assert_report("linux", complete_report(), "abc1234") == []
    assert evidence.assert_report("macos", complete_report("macos"), "abc1234") == []


def test_candidate_report_contract_rejects_incomplete_manual_and_commit_evidence():
    report = complete_report()
    report["expectedCommit"] = "different"
    report["manualChecklist"]["nativeVisuals"] = "pending"
    failures = evidence.assert_report("linux", report, "abc1234")
    assert any("commit" in failure for failure in failures)
    assert any("manual checklist" in failure for failure in failures)


def test_stdlib_fake_model_emits_sse_and_redacts_auth_in_transcript():
    fake = journey.FakeOpenAI()
    fake.start()
    try:
        request = urllib.request.Request(
            fake.base_url + "/v1/chat/completions",
            data=json.dumps({"model": "e2e-model"}).encode(),
            headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode()
        assert "Harness reply" in body
        assert "[DONE]" in body
        assert fake.transcript == [
            {
                "path": "/v1/chat/completions",
                "model": "e2e-model",
                "authorization": "[redacted]",
                "at": fake.transcript[0]["at"],
            }
        ]
    finally:
        fake.stop()
