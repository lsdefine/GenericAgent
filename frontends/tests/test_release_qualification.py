import importlib.util
import io
import json
import plistlib
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


journey = load_module(
    "run_release_qualification",
    "frontends/desktop/release_qualification/run_release_qualification.py",
)
evidence = load_module(
    "verify_release_evidence",
    "frontends/desktop/release_qualification/verify_release_evidence.py",
)


def complete_report(platform: str = "linux"):
    checks = {name: True for name in evidence.COMMON_CHECKS}
    isolated_port = 29890
    ownership = {
        scenario: owned_conductor(port=isolated_port, pid=44120 + index)
        for index, scenario in enumerate(sorted(evidence.SUCCESSFUL_APPLICATION_SCENARIOS))
    }
    checks["isolatedConductorOwnership"] = ownership
    checks["ownedProcessStops"] = {
        scenario: {
            "app": 45120 + index * 3,
            "bridge": 45121 + index * 3,
            "conductor": ownership[scenario]["pid"],
        }
        for index, scenario in enumerate(sorted(evidence.SUCCESSFUL_APPLICATION_SCENARIOS))
    }
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
        "releaseVersion": "0.2.1",
        "artifact": {"sha256": "f" * 64},
        "environment": {"isolatedConductorPort": isolated_port},
        "success": True,
        "checks": checks,
        "bootstrap": bootstrap,
        "manualChecklist": {"nativeVisuals": "pass"},
        "screenshots": ["ready.png", "foreign.png"],
    }


def test_candidate_report_contract_accepts_complete_platform_evidence():
    assert evidence.assert_report("linux", complete_report(), "abc1234") == []
    assert evidence.assert_report("macos", complete_report("macos"), "abc1234") == []


def test_automated_gate_ignores_manual_evidence_but_rejects_commit_mismatch():
    report = complete_report()
    report["manualChecklist"]["nativeVisuals"] = "pending"
    report["screenshots"] = []
    assert evidence.assert_report("linux", report, "abc1234") == []

    report["expectedCommit"] = "different"
    failures = evidence.assert_report("linux", report, "abc1234")
    assert any("commit" in failure for failure in failures)


def test_combined_gate_ignores_platform_and_windows_native_manual_review(
    tmp_path, monkeypatch
):
    report_paths = {}
    for platform in ("windows", "linux", "macos"):
        report = complete_report(platform)
        report["manualChecklist"] = {"nativeVisuals": "pending"}
        report["screenshots"] = []
        path = tmp_path / f"{platform}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        report_paths[platform] = path

    windows_native = tmp_path / "windows-native.json"
    windows_native.write_text(
        json.dumps(
            {
                "success": True,
                "checks": {"portConflictRecovery": True, "settingsRestored": True},
                "manualChecklist": {"nativeVisuals": "manual"},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "manifest.json"
    monkeypatch.setattr(
        evidence.sys,
        "argv",
        [
            "verify_release_evidence.py",
            "--expected-commit",
            "abc1234",
            "--windows",
            str(report_paths["windows"]),
            "--linux",
            str(report_paths["linux"]),
            "--macos",
            str(report_paths["macos"]),
            "--windows-native-report",
            str(windows_native),
            "--output",
            str(output),
        ],
    )

    assert evidence.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["gate"] == "pass"


def test_candidate_report_contract_rejects_partial_or_unowned_conductor_evidence():
    report = complete_report()
    report["checks"]["isolatedConductorOwnership"].pop("relocated")
    report["checks"]["ownedProcessStops"]["warm-restart"].pop("conductor")

    failures = evidence.assert_report("linux", report, "abc1234")

    assert any("ownership does not cover every successful launch" in item for item in failures)
    assert any("invalid owned process stop evidence for warm-restart" in item for item in failures)


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


def write_info_plist(root: Path, **overrides):
    contents = root / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    values = {
        "CFBundleShortVersionString": "0.2.1",
        "CFBundleVersion": "0.2.1",
        **overrides,
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(values, stream)


def test_macos_package_version_comes_from_both_native_bundle_keys(tmp_path):
    write_info_plist(tmp_path)
    assert journey.read_macos_bundle_versions(tmp_path) == ("0.2.1", "0.2.1")


@pytest.mark.parametrize("key", ["CFBundleShortVersionString", "CFBundleVersion"])
@pytest.mark.parametrize("value", ["0.2.0", 200])
def test_macos_package_version_rejects_wrong_or_non_string_keys(tmp_path, key, value):
    write_info_plist(tmp_path, **{key: value})
    with pytest.raises(journey.JourneyFailure, match=key):
        journey.read_macos_bundle_versions(tmp_path)


@pytest.mark.parametrize("key", ["CFBundleShortVersionString", "CFBundleVersion"])
def test_macos_package_version_rejects_missing_keys(tmp_path, key):
    write_info_plist(tmp_path)
    path = tmp_path / "Contents" / "Info.plist"
    with path.open("rb") as stream:
        values = plistlib.load(stream)
    del values[key]
    with path.open("wb") as stream:
        plistlib.dump(values, stream)
    with pytest.raises(journey.JourneyFailure, match=key):
        journey.read_macos_bundle_versions(tmp_path)


@pytest.mark.parametrize("payload", [b"not a plist", b"", plistlib.dumps([])])
def test_macos_package_version_rejects_invalid_or_empty_plist(tmp_path, payload):
    contents = tmp_path / "Contents"
    contents.mkdir()
    (contents / "Info.plist").write_bytes(payload)
    with pytest.raises(journey.JourneyFailure, match="missing or invalid"):
        journey.read_macos_bundle_versions(tmp_path)


def test_macos_package_version_rejects_missing_plist(tmp_path):
    with pytest.raises(journey.JourneyFailure, match="missing or invalid"):
        journey.read_macos_bundle_versions(tmp_path)


def test_package_shape_rejects_excluded_source_package_json(tmp_path):
    package_root = tmp_path / "GenericAgent.app"
    runtime_root = package_root / "Contents" / "Resources" / "runtime"
    application = package_root / "Contents" / "MacOS" / "GenericAgent"
    for path in [
        application,
        runtime_root / "app" / "agentmain.py",
        runtime_root / "app" / "frontends" / "desktop_bridge.py",
        runtime_root / "app" / "frontends" / "desktop" / "static" / "index.html",
        runtime_root / "python" / "bin" / "python3",
        runtime_root / ".prepared",
        runtime_root / "app" / "frontends" / "desktop" / "package.json",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    write_info_plist(package_root)

    candidate = object.__new__(journey.Journey)
    candidate.args = type("Args", (), {"platform": "macos"})()
    candidate.package_root = package_root
    candidate.runtime_root = runtime_root
    candidate.application = application
    candidate.report = {"checks": {}}

    with pytest.raises(journey.JourneyFailure, match="excluded Desktop source metadata"):
        candidate.check_package_shape()

    (runtime_root / "app" / "frontends" / "desktop" / "package.json").unlink()
    candidate.check_package_shape()
    assert candidate.report["checks"] == {
        "packagedVersion": "0.2.1",
        "packagedBundleVersion": "0.2.1",
        "packageShape": True,
    }


def chat_snapshot(*, status="idle", unfinished=False):
    return {
        "status": status,
        "hasUnfinishedWork": unfinished,
        "messages": [{"role": "assistant", "content": "Harness reply"}],
        "lastError": "model failed" if status == "error" else "",
    }


def test_package_chat_waits_for_the_live_turn_thread_after_reply_and_idle_status():
    assert journey.completed_assistant_reply(chat_snapshot(status="running", unfinished=True)) is None
    assert journey.completed_assistant_reply(chat_snapshot(unfinished=True)) is None
    assert journey.completed_assistant_reply(chat_snapshot()) == "Harness reply"

    missing_barrier = chat_snapshot()
    missing_barrier.pop("hasUnfinishedWork")
    assert journey.completed_assistant_reply(missing_barrier) is None


@pytest.mark.parametrize("status", ["error", "cancelled"])
def test_package_chat_fails_immediately_on_terminal_session_state(status):
    with pytest.raises(journey.JourneyFailure, match=f"terminal state {status}"):
        journey.completed_assistant_reply(chat_snapshot(status=status))


def valid_import_conflict():
    return {
        "ok": False,
        "error": "managed Desktop services are running",
        "code": "maintenance_conflict",
        "runningSessions": [],
        "runningExtras": ["frontends/conductor.py", "reflect/scheduler.py"],
    }


def test_package_import_requires_the_exact_running_extras_conflict():
    assert journey.validate_import_maintenance_conflict(409, valid_import_conflict()) == [
        "frontends/conductor.py",
        "reflect/scheduler.py",
    ]


def test_package_request_reads_the_expected_http_error_json(monkeypatch):
    payload = {**valid_import_conflict(), "runningExtras": ["frontends/conductor.py"]}
    error = urllib.error.HTTPError(
        "http://127.0.0.1:14168/memory/import",
        409,
        "Conflict",
        {},
        io.BytesIO(json.dumps(payload).encode("utf-8")),
    )

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    status, response = journey.request_json_with_status(
        "POST",
        "/memory/import",
        {"sourceDir": "/source"},
    )

    assert status == 409
    assert response == payload


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (200, valid_import_conflict()),
        (409, {**valid_import_conflict(), "ok": True}),
        (409, {**valid_import_conflict(), "code": "other_conflict"}),
        (409, {**valid_import_conflict(), "runningSessions": ["sess-live"]}),
        (409, {**valid_import_conflict(), "runningExtras": []}),
        (409, {**valid_import_conflict(), "runningExtras": ["reflect/scheduler.py"]}),
        (409, {**valid_import_conflict(), "runningExtras": ["frontends/conductor.py"] * 2}),
    ],
)
def test_package_import_rejects_inexact_maintenance_conflicts(status, payload):
    with pytest.raises(journey.JourneyFailure):
        journey.validate_import_maintenance_conflict(status, payload)


def stopped_panel(*services):
    return {"services": list(services)}


def owned_conductor(port=29890, pid=44123):
    return {
        "id": "frontends/conductor.py",
        "status": "running",
        "running": True,
        "owned": True,
        "external": False,
        "port": port,
        "pid": pid,
    }


def test_package_journey_requires_exact_owned_isolated_conductor_state():
    state = owned_conductor()
    payload = stopped_panel(state)
    assert journey.verified_owned_conductor(payload, 29890, True) is state
    assert journey.verified_owned_conductor(payload, 29890, False) is None

    mutations = [
        {**state, "status": "error"},
        {**state, "running": False},
        {**state, "owned": False},
        {**state, "external": True},
        {**state, "port": 8900},
        {**state, "pid": None},
    ]
    for mutation in mutations:
        assert journey.verified_owned_conductor(stopped_panel(mutation), 29890, True) is None
    assert journey.verified_owned_conductor(stopped_panel(state, state), 29890, True) is None


def test_package_start_injects_only_the_isolated_e2e_conductor_port(tmp_path, monkeypatch):
    candidate = object.__new__(journey.Journey)
    candidate.process = None
    candidate.package_root = tmp_path
    candidate.application = tmp_path / "GenericAgent"
    candidate.report_dir = tmp_path / "reports"
    candidate.conductor_port = 29890
    candidate.process_log = None
    candidate.report = {"pids": []}
    captured = {}

    class FakeProcess:
        pid = 44120

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(journey, "loopback_port_is_free", lambda port: port == 29890)
    monkeypatch.setattr(journey.subprocess, "Popen", fake_popen)

    candidate.start_application("first-launch")
    candidate.process_log.close()

    assert captured["env"]["GA_DESKTOP_E2E_CONDUCTOR_PORT"] == "29890"
    assert Path(captured["env"]["GA_DESKTOP_E2E_REPORT_DIR"]).parts[-2:] == (
        "bootstrap",
        "first-launch",
    )
    assert candidate.report["pids"] == [{"scenario": "first-launch", "app": 44120}]


def test_isolated_conductor_allocator_rejects_active_and_default_product_ports(monkeypatch):
    candidates = iter([24170, 14168, 8900, 29890])

    class FakeReservation:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def bind(self, _address):
            return None

        def getsockname(self):
            return ("127.0.0.1", next(candidates))

    monkeypatch.setattr(journey, "BRIDGE_PORT", 24170)
    monkeypatch.setattr(journey.socket, "socket", lambda *_args, **_kwargs: FakeReservation())

    assert journey.allocate_isolated_conductor_port() == 29890


def test_every_successful_ready_snapshot_records_its_owned_conductor_pid(
    tmp_path, monkeypatch
):
    candidate = object.__new__(journey.Journey)
    candidate.args = SimpleNamespace(start_timeout=1, expected_commit="abc1234")
    candidate.report_dir = tmp_path / "report"
    candidate.external_root = tmp_path / "external"
    candidate.runtime_root = tmp_path / "package" / "runtime"
    candidate.conductor_port = 29890
    candidate.report = {
        "bootstrap": {},
        "identities": {},
        "pids": [{"scenario": "warm-restart", "app": 44120}],
        "checks": {},
    }
    expected_app_dir = candidate.runtime_root / "app" / "frontends"
    latest = candidate.scenario_dir("warm-restart") / "bootstrap-latest.json"
    journey.write_json(latest, {"phase": "ready"})

    def fake_request(_method, path, body=None, timeout=5.0):
        del body, timeout
        if path == "/services/identity":
            return {
                "ga_root": str(candidate.external_root),
                "app_dir": str(expected_app_dir),
                "pid": 44121,
                "build_id": "desktop-abc1234",
            }
        if path == "/services/panel":
            return stopped_panel(owned_conductor(pid=44122))
        raise AssertionError(path)

    monkeypatch.setattr(journey, "request_json", fake_request)
    monkeypatch.setattr(
        journey,
        "loopback_port_is_free",
        lambda port: False if port == 29890 else True,
    )

    candidate.wait_ready("warm-restart", candidate.external_root)

    assert candidate.report["pids"][-1]["bridge"] == 44121
    assert candidate.report["pids"][-1]["conductor"] == 44122
    assert candidate.report["checks"]["isolatedConductorOwnership"] == {
        "warm-restart": owned_conductor(pid=44122)
    }


def test_package_import_waits_until_every_reported_extra_is_offline():
    ids = ["frontends/conductor.py", "reflect/scheduler.py"]
    complete = stopped_panel(
        {"id": "frontends/conductor.py", "running": False, "status": "offline"},
        {"id": "reflect/scheduler.py", "running": False, "status": "offline"},
    )
    assert journey.verified_stopped_extras_panel(complete, ids) is complete
    assert journey.verified_stopped_extras_panel(
        stopped_panel({"id": ids[0], "running": False, "status": "offline"}),
        ids,
    ) is None
    assert journey.verified_stopped_extras_panel(
        stopped_panel(
            {"id": ids[0], "running": False, "status": "offline"},
            {"id": ids[1], "running": True, "status": "running"},
        ),
        ids,
    ) is None
    assert journey.verified_stopped_extras_panel(
        stopped_panel(
            {"id": ids[0], "running": False, "status": "offline"},
            {"id": ids[1], "running": False, "status": "error"},
        ),
        ids,
    ) is None


def test_real_package_memory_import_stops_reported_extras_before_one_successful_import(
    tmp_path, monkeypatch
):
    candidate = object.__new__(journey.Journey)
    candidate.external_root = tmp_path / "external"
    candidate.work_dir = tmp_path / "work"
    candidate.fake = SimpleNamespace(transcript=[{"model": "e2e-model"}])
    candidate.report = {"checks": {}}
    sid = "sess-package-test"
    session_file = candidate.external_root / "temp" / "desktop_sessions" / f"{sid}.json"
    imported_sid = "sess-p2-package-imported"
    stopped = False
    calls = []

    def fake_request(method, path, body=None, timeout=5.0):
        nonlocal stopped
        calls.append((method, path))
        if path == "/session/new":
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text('{"id":"sess-package-test"}\n', encoding="utf-8")
            return {"sessionId": sid}
        if path == "/upload":
            upload = candidate.external_root / "temp" / "desktop_uploads" / "p2.png"
            upload.parent.mkdir(parents=True, exist_ok=True)
            upload.write_bytes(b"png")
            return {"ok": True, "path": str(upload)}
        if path.endswith("/prompt"):
            return {"ok": True}
        if path.endswith("/messages?limit=20"):
            return chat_snapshot()
        if path == "/services/stop-extras":
            stopped = True
            return {"ok": True}
        if path == "/services/panel":
            assert stopped is True
            return stopped_panel(
                {"id": "frontends/conductor.py", "running": False, "status": "offline"}
            )
        if path == "/memory/import":
            assert stopped is True
            source = Path(body["sourceDir"])
            memory = candidate.external_root / "memory" / "p2-package-memory.txt"
            responses = candidate.external_root / "temp" / "model_responses"
            backup = candidate.external_root / "temp" / "memory_import_backup_test"
            (backup / "memory").mkdir(parents=True)
            (backup / "memory" / memory.name).write_bytes(memory.read_bytes())
            memory.write_bytes((source / "memory" / memory.name).read_bytes())
            (responses / "new.json").write_bytes(
                (source / "temp" / "model_responses" / "new.json").read_bytes()
            )
            imported = candidate.external_root / "temp" / "desktop_sessions" / f"{imported_sid}.json"
            imported.write_bytes(
                (source / "temp" / "desktop_sessions" / imported.name).read_bytes()
            )
            return {
                "ok": True,
                "memoryCopied": 1,
                "responsesCopied": 1,
                "responsesSkipped": 1,
                "sessionsAdded": 1,
                "backupDir": str(backup),
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    def fake_conflict(method, path, body=None, timeout=5.0):
        calls.append((method, f"{path}:expected-conflict"))
        memory = candidate.external_root / "memory" / "p2-package-memory.txt"
        responses = candidate.external_root / "temp" / "model_responses"
        assert memory.read_text(encoding="utf-8") == "before\n"
        assert (responses / "shared.json").read_text(encoding="utf-8") == "destination\n"
        assert not (responses / "new.json").exists()
        assert session_file.read_text(encoding="utf-8") == '{"id":"sess-package-test"}\n'
        return 409, {**valid_import_conflict(), "runningExtras": ["frontends/conductor.py"]}

    monkeypatch.setattr(journey, "request_json", fake_request)
    monkeypatch.setattr(journey, "request_json_with_status", fake_conflict)

    candidate.run_chat_upload_memory()

    assert calls == [
        ("POST", "/session/new"),
        ("POST", "/upload"),
        ("POST", f"/session/{sid}/prompt"),
        ("GET", f"/session/{sid}/messages?limit=20"),
        ("POST", "/memory/import:expected-conflict"),
        ("POST", "/services/stop-extras"),
        ("GET", "/services/panel"),
        ("POST", "/memory/import"),
    ]
    gate = candidate.report["checks"]["memoryImportMaintenanceGate"]
    assert gate["runningSessions"] == []
    assert gate["runningExtras"] == ["frontends/conductor.py"]
    assert candidate.report["checks"]["memoryImport"]["ok"] is True
