#!/usr/bin/env python3
"""Cross-platform release-package journey for GenericAgent Desktop 2.0.

This runner deliberately exercises a production binary and its packaged runtime.  It does
not import product code from the checkout and it does not require network access.  The
platform wrappers are responsible for extracting/installing the artifact and then pass the
application/runtime paths here.

The production binary uses the real per-user settings file, so the runner refuses to start
without an explicit acknowledgement.  It backs up that file byte-for-byte and restores it in
``finally``.  Run this only in a dedicated OS test account: macOS may also create its normal
versioned writable runtime under Application Support during the stale-override fallback test.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.server
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 14168
BRIDGE_BASE = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
RELEASE_VERSION = "0.2.0"


class JourneyFailure(RuntimeError):
    pass


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def is_within(child: Path | str, parent: Path | str) -> bool:
    try:
        canonical(child).relative_to(canonical(parent))
        return True
    except (OSError, ValueError):
        return False


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_json(method: str, path: str, body: Any = None, timeout: float = 5.0) -> Any:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(f"{BRIDGE_BASE}{path}", data=payload, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_until(label: str, predicate, timeout: float, interval: float = 0.25) -> Any:
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as error:
            last_error = error
        time.sleep(interval)
    suffix = f": {last_error}" if last_error else ""
    raise JourneyFailure(f"timed out waiting for {label}{suffix}")


def port_is_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex((BRIDGE_HOST, BRIDGE_PORT)) != 0


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class FakeOpenAIHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        self.server.transcript.append({  # type: ignore[attr-defined]
            "path": self.path,
            "model": body.get("model", ""),
            "authorization": "[redacted]" if self.headers.get("Authorization") else "",
            "at": utc_now(),
        })
        events = [
            {"choices": [{"delta": {"content": "Harness reply"}}]},
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 101,
                    "completion_tokens": 17,
                    "prompt_tokens_details": {"cached_tokens": 11},
                },
            },
        ]
        data = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        data += "data: [DONE]\n\n"
        encoded = data.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)


class FakeOpenAI:
    def __init__(self) -> None:
        self.server = http.server.ThreadingHTTPServer((BRIDGE_HOST, 0), FakeOpenAIHandler)
        self.server.transcript = []  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.started = False

    @property
    def base_url(self) -> str:
        return f"http://{BRIDGE_HOST}:{self.server.server_port}"

    @property
    def transcript(self) -> list[dict[str, Any]]:
        return list(self.server.transcript)  # type: ignore[attr-defined]

    def start(self) -> None:
        self.thread.start()
        self.started = True

    def stop(self) -> None:
        if self.started:
            self.server.shutdown()
        self.server.server_close()
        if self.started:
            self.thread.join(timeout=5)


class ForeignIdentityHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        payload = json.dumps({"service": "foreign-p2-package-listener", "pid": os.getpid()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def fake_mykey(base_url: str) -> str:
    return "\n".join(
        [
            "native_oai_config = {",
            "    'name': 'GenericAgent package E2E',",
            "    'apikey': 'e2e-dummy-key',",
            f"    'apibase': {str(base_url + '/v1')!r},",
            "    'model': 'e2e-model',",
            "    'api_mode': 'chat_completions',",
            "    'stream': True,",
            "    'max_retries': 0,",
            "    'connect_timeout': 2,",
            "    'read_timeout': 30,",
            "}",
            "",
        ]
    )


def tree_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            snapshot[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def capture_screenshot(target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    commands: list[list[str]] = []
    if system == "Darwin":
        commands = [["screencapture", "-x", str(target)]]
    elif system == "Linux":
        commands = [
            ["gnome-screenshot", "-f", str(target)],
            ["scrot", str(target)],
            ["import", "-window", "root", str(target)],
        ]
    for command in commands:
        if not shutil.which(command[0]):
            continue
        completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if completed.returncode == 0 and target.is_file() and target.stat().st_size > 0:
            return True
    return False


class Journey:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.package_root = canonical(args.package_root)
        self.application_relative = Path(args.application_relative)
        self.runtime_relative = Path(args.runtime_relative)
        self.runtime_root = self.package_root / self.runtime_relative
        self.application = self.package_root / self.application_relative
        self.report_dir = canonical(args.report_dir)
        self.work_dir = canonical(args.work_dir)
        self.settings_path = Path.home() / ".ga_desktop_settings.json"
        self.settings_existed = self.settings_path.exists()
        self.settings_bytes = self.settings_path.read_bytes() if self.settings_existed else b""
        self.settings_mode = self.settings_path.stat().st_mode if self.settings_existed else None
        self.fake = FakeOpenAI()
        self.external_root = self.work_dir / "external compatible core"
        self.stale_root = self.work_dir / "external compatible core.removed"
        self.process: subprocess.Popen[bytes] | None = None
        self.process_log = None
        self.foreign_server: http.server.ThreadingHTTPServer | None = None
        self.foreign_thread: threading.Thread | None = None
        self.screenshots: list[str] = []
        self.app_snapshot: dict[str, tuple[int, int]] | None = None
        self.report: dict[str, Any] = {
            "schemaVersion": 1,
            "startedAt": utc_now(),
            "expectedCommit": args.expected_commit,
            "releaseVersion": RELEASE_VERSION,
            "artifact": {},
            "environment": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "architecture": platform.machine(),
                "python": platform.python_version(),
            },
            "paths": {"before": str(self.package_root)},
            "checks": {},
            "bootstrap": {},
            "identities": {},
            "pids": [],
            "screenshots": self.screenshots,
            "manualChecklist": self.manual_checklist(args.platform),
            "failures": [],
        }

    @staticmethod
    def manual_checklist(system: str) -> dict[str, str]:
        common = {
            "loadingFallbackAndMainRender": "pending",
            "nativeDirectoryPicker": "pending",
            "noVisualRegression": "pending",
        }
        platform_items = {
            "windows": {
                "framelessTitlebarAndThreeButtons": "pending",
                "trayAndCloseHides": "pending",
                "shortcutSelfHealsAfterMove": "pending",
            },
            "linux": {
                "appImageExecutableAndDesktopLauncher": "pending",
                "windowDragAndCloseBehavior": "pending",
                "retryButtonAfterPortRelease": "pending",
            },
            "macos": {
                "gatekeeperOrOpenAnyway": "pending",
                "trafficLightsAndWindowFocus": "pending",
                "retryButtonAfterPortRelease": "pending",
            },
        }
        return {**common, **platform_items[system]}

    def check_package_shape(self) -> None:
        required = [
            self.application,
            self.runtime_root / "app" / "agentmain.py",
            self.runtime_root / "app" / "frontends" / "desktop_bridge.py",
            self.runtime_root / "app" / "frontends" / "desktop" / "static" / "index.html",
        ]
        python = self.runtime_root / "python" / ("python.exe" if self.args.platform == "windows" else "bin/python3")
        required.append(python)
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise JourneyFailure(f"package paths are missing: {missing}")
        package_json = read_json(self.runtime_root / "app" / "frontends" / "desktop" / "package.json", {})
        if package_json.get("version") != RELEASE_VERSION:
            raise JourneyFailure(f"packaged package.json version is {package_json.get('version')!r}")
        if self.args.platform == "macos" and not (self.runtime_root / ".prepared").is_file():
            raise JourneyFailure("macOS package has no build-time .prepared marker")
        self.report["checks"]["packageShape"] = True
        self.report["checks"]["packagedVersion"] = package_json.get("version")

    def prepare_external_root(self) -> None:
        if self.external_root.exists() or self.stale_root.exists():
            raise JourneyFailure(f"test work directory is not clean: {self.work_dir}")
        shutil.copytree(self.runtime_root / "app", self.external_root, symlinks=True)
        (self.external_root / "mykey.py").write_text(fake_mykey(self.fake.base_url), encoding="utf-8")
        write_json(
            self.settings_path,
            {"lang": "en", "ga_source_override": str(self.external_root), "ui": {"llmNo": 0}},
        )

    def scenario_dir(self, name: str) -> Path:
        path = self.report_dir / "bootstrap" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def start_application(self, scenario: str) -> None:
        if self.process is not None:
            raise JourneyFailure("application is already running")
        report = self.scenario_dir(scenario)
        log_path = self.report_dir / "logs" / f"{scenario}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.process_log = log_path.open("wb")
        env = os.environ.copy()
        env["GA_DESKTOP_E2E_REPORT_DIR"] = str(report)
        self.process = subprocess.Popen(
            [str(self.application)],
            cwd=str(self.package_root),
            env=env,
            stdout=self.process_log,
            stderr=subprocess.STDOUT,
        )
        self.report["pids"].append({"scenario": scenario, "app": self.process.pid})

    def stop_application(self) -> None:
        with contextlib.suppress(Exception):
            request_json("POST", "/services/bridge/exit", {}, timeout=2)
        if self.process is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.process.terminate()
                self.process.wait(timeout=8)
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None
        if self.process_log is not None:
            self.process_log.close()
            self.process_log = None
        wait_until("bridge port cleanup", port_is_free, 20)

    def wait_ready(self, scenario: str, expected_root: Path | None) -> dict[str, Any]:
        latest = self.scenario_dir(scenario) / "bootstrap-latest.json"

        def ready_snapshot() -> dict[str, Any] | None:
            value = read_json(latest, {})
            if value.get("phase") == "failed":
                raise JourneyFailure(f"bootstrap failed in {scenario}: {value.get('failure')}")
            return value if value.get("phase") == "ready" else None

        snapshot = wait_until(f"{scenario} bootstrap ready", ready_snapshot, self.args.start_timeout)

        def expected_identity() -> dict[str, Any] | None:
            value = request_json("GET", "/services/identity", timeout=2)
            if not value.get("ga_root") or not value.get("app_dir") or not value.get("pid"):
                return None
            if expected_root is not None and canonical(value["ga_root"]) != canonical(expected_root):
                return None
            return value

        identity = wait_until(f"{scenario} bridge identity", expected_identity, 30)
        if is_within(identity["app_dir"], self.external_root):
            raise JourneyFailure("desktop bridge came from external GA_ROOT instead of the package")
        expected_app_dir = self.runtime_root / "app" / "frontends"
        if canonical(identity["app_dir"]) != canonical(expected_app_dir):
            raise JourneyFailure(
                f"package bridge app_dir mismatch: {identity['app_dir']} != {expected_app_dir}"
            )
        build_id = str(identity.get("build_id", ""))
        expected = self.args.expected_commit.strip().lower()
        if expected and expected[:7] not in build_id.lower():
            raise JourneyFailure(f"bridge build_id {build_id!r} does not contain commit {expected[:7]}")
        self.report["bootstrap"][scenario] = snapshot
        self.report["identities"][scenario] = identity
        self.report["pids"][-1]["bridge"] = identity["pid"]
        return identity

    def run_chat_upload_memory(self) -> None:
        session = request_json("POST", "/session/new", {"cwd": str(self.external_root)})
        sid = session.get("sessionId")
        if not sid:
            raise JourneyFailure(f"session creation failed: {session}")
        tiny_png = base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        ).decode()
        uploaded = request_json(
            "POST",
            "/upload",
            {"name": "p2.png", "dataUrl": f"data:image/png;base64,{tiny_png}", "sid": sid},
        )
        upload_path = Path(str(uploaded.get("path", "")))
        if not uploaded.get("ok") or not upload_path.is_file() or not is_within(upload_path, self.external_root):
            raise JourneyFailure(f"package upload did not stay under GA_ROOT: {uploaded}")
        accepted = request_json(
            "POST",
            f"/session/{sid}/prompt",
            {"prompt": "[E2E:normal] release package smoke", "display": "release package smoke"},
        )
        if not accepted.get("ok"):
            raise JourneyFailure(f"chat prompt was rejected: {accepted}")

        def assistant_reply() -> str | None:
            value = request_json("GET", f"/session/{sid}/messages?limit=20", timeout=3)
            for message in reversed(value.get("messages", [])):
                if message.get("role") == "assistant" and "Harness reply" in message.get("content", ""):
                    return message["content"]
            if value.get("status") == "error":
                raise JourneyFailure(f"chat failed: {value.get('lastError')}")
            return None

        wait_until("deterministic package chat reply", assistant_reply, 90, 0.5)
        if not self.fake.transcript:
            raise JourneyFailure("fake model received no request")

        source = self.work_dir / "memory import source"
        source_memory = source / "memory"
        source_responses = source / "temp" / "model_responses"
        source_sessions = source / "temp" / "desktop_sessions"
        destination_memory = self.external_root / "memory"
        destination_responses = self.external_root / "temp" / "model_responses"
        for directory in (source_memory, source_responses, source_sessions, destination_memory, destination_responses):
            directory.mkdir(parents=True, exist_ok=True)
        (destination_memory / "p2-package-memory.txt").write_text("before\n", encoding="utf-8")
        (source_memory / "p2-package-memory.txt").write_text("after\n", encoding="utf-8")
        (destination_responses / "shared.json").write_text("destination\n", encoding="utf-8")
        (source_responses / "shared.json").write_text("source-must-not-win\n", encoding="utf-8")
        (source_responses / "new.json").write_text("new\n", encoding="utf-8")
        current_session_file = self.external_root / "temp" / "desktop_sessions" / f"{sid}.json"
        wait_until("persisted package session", current_session_file.is_file, 10)
        shutil.copy2(current_session_file, source_sessions / current_session_file.name)
        imported_sid = "sess-p2-package-imported"
        write_json(
            source_sessions / f"{imported_sid}.json",
            {
                "id": imported_sid,
                "title": "P2 imported",
                "messages": [],
                "msg_seq": 0,
                "cwd": str(source),
                "created_at": time.time(),
                "updated_at": time.time(),
            },
        )
        result = request_json("POST", "/memory/import", {"sourceDir": str(source)}, timeout=20)
        required_fields = {
            "memoryCopied",
            "responsesCopied",
            "responsesSkipped",
            "sessionsAdded",
            "backupDir",
        }
        if not result.get("ok") or not required_fields.issubset(result):
            raise JourneyFailure(f"memory import response contract failed: {result}")
        backup_file = Path(result["backupDir"]) / "memory" / "p2-package-memory.txt"
        if backup_file.read_text(encoding="utf-8") != "before\n":
            raise JourneyFailure("memory import did not preserve the pre-import backup")
        if (destination_memory / "p2-package-memory.txt").read_text(encoding="utf-8") != "after\n":
            raise JourneyFailure("memory import did not overwrite memory")
        if (destination_responses / "shared.json").read_text(encoding="utf-8") != "destination\n":
            raise JourneyFailure("memory import overwrote an existing response")
        if not (destination_responses / "new.json").is_file() or result["sessionsAdded"] != 1:
            raise JourneyFailure(f"memory response/session merge failed: {result}")
        self.report["checks"].update(
            {
                "deterministicChat": True,
                "uploadUnderExternalRoot": True,
                "memoryImport": result,
                "fakeModelRequests": self.fake.transcript,
            }
        )

    def run_port_conflict(self) -> None:
        if not port_is_free():
            raise JourneyFailure("bridge port was not released before foreign-port test")
        self.foreign_server = http.server.ThreadingHTTPServer(
            (BRIDGE_HOST, BRIDGE_PORT), ForeignIdentityHandler
        )
        self.foreign_thread = threading.Thread(target=self.foreign_server.serve_forever, daemon=True)
        self.foreign_thread.start()
        self.start_application("foreign-port")
        latest = self.scenario_dir("foreign-port") / "bootstrap-latest.json"

        def failed_snapshot() -> dict[str, Any] | None:
            value = read_json(latest, {})
            return value if value.get("phase") == "failed" else None

        failed = wait_until("foreign port bootstrap failure", failed_snapshot, 90)
        if failed.get("failure", {}).get("code") != "port_conflict":
            raise JourneyFailure(f"foreign port produced the wrong failure: {failed}")
        if self.foreign_thread is None or not self.foreign_thread.is_alive():
            raise JourneyFailure("desktop terminated the foreign listener")
        self.report["bootstrap"]["foreign-port"] = failed
        self.report["checks"]["foreignListenerSurvived"] = True
        screenshot = self.report_dir / "screenshots" / "foreign-port.png"
        if capture_screenshot(screenshot):
            self.screenshots.append(str(screenshot))
        if self.process is not None:
            self.process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=8)
            if self.process.poll() is None:
                self.process.kill()
            self.process = None
        if self.process_log is not None:
            self.process_log.close()
            self.process_log = None
        self.foreign_server.shutdown()
        self.foreign_server.server_close()
        self.foreign_server = None
        if self.foreign_thread:
            self.foreign_thread.join(timeout=5)
            self.foreign_thread = None
        wait_until("foreign port release", port_is_free, 10)
        self.start_application("after-port-release")
        self.wait_ready("after-port-release", self.external_root)
        self.report["checks"]["portRecovery"] = "release-then-production-restart"

    def relocate_package(self) -> None:
        self.stop_application()
        destination = canonical(self.args.relocated_root)
        if destination.exists():
            raise JourneyFailure(f"relocation target already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.package_root), str(destination))
        self.package_root = destination
        self.application = destination / self.application_relative
        self.runtime_root = destination / self.runtime_relative
        self.report["paths"]["after"] = str(destination)
        self.start_application("relocated")
        identity = self.wait_ready("relocated", self.external_root)
        if not is_within(identity["app_dir"], destination):
            raise JourneyFailure("relocated package still reported the previous package path")
        self.report["checks"]["relocation"] = True

    def stale_override_fallback(self) -> None:
        self.stop_application()
        self.external_root.rename(self.stale_root)
        self.start_application("stale-override")
        identity = self.wait_ready("stale-override", None)
        if canonical(identity["ga_root"]) == canonical(self.external_root):
            raise JourneyFailure("deleted GA_ROOT override did not fall back")
        fallback = canonical(identity["ga_root"])
        if not (fallback / "agentmain.py").is_file():
            raise JourneyFailure(f"fallback GA_ROOT is not a usable core: {fallback}")
        panel = request_json("GET", "/services/panel", timeout=5)
        if "services" not in panel:
            raise JourneyFailure(f"service panel failed with optional P2P dependencies absent: {panel}")
        self.report["checks"]["staleOverrideFallback"] = str(fallback)
        self.report["checks"]["optionalP2PDoesNotBlockReady"] = True

    def restore_settings(self) -> None:
        if self.settings_existed:
            self.settings_path.write_bytes(self.settings_bytes)
            if self.settings_mode is not None:
                os.chmod(self.settings_path, self.settings_mode)
        else:
            with contextlib.suppress(FileNotFoundError):
                self.settings_path.unlink()

    def cleanup(self) -> None:
        with contextlib.suppress(Exception):
            self.stop_application()
        with contextlib.suppress(Exception):
            if self.foreign_server is not None:
                self.foreign_server.shutdown()
                self.foreign_server.server_close()
        with contextlib.suppress(Exception):
            if self.foreign_thread is not None:
                self.foreign_thread.join(timeout=5)
        with contextlib.suppress(Exception):
            self.fake.stop()
        with contextlib.suppress(Exception):
            if self.stale_root.exists() and not self.external_root.exists():
                self.stale_root.rename(self.external_root)
        self.restore_settings()
        self.report["checks"]["settingsRestored"] = (
            self.settings_path.read_bytes() == self.settings_bytes
            if self.settings_existed
            else not self.settings_path.exists()
        )
        self.report["checks"]["finalPortFree"] = port_is_free()
        owned_pids = {
            int(pid)
            for item in self.report["pids"]
            for pid in (item.get("app"), item.get("bridge"))
            if isinstance(pid, int) and pid > 0
        }
        deadline = time.monotonic() + 10
        while any(pid_is_alive(pid) for pid in owned_pids) and time.monotonic() < deadline:
            time.sleep(0.2)
        alive_pids = sorted(pid for pid in owned_pids if pid_is_alive(pid))
        self.report["checks"]["finalAliveOwnedPids"] = alive_pids
        self.report["checks"]["finalOwnedProcessesExited"] = not alive_pids

    def save_report(self, success: bool) -> None:
        self.report["success"] = success
        self.report["manualComplete"] = all(
            value == "pass" for value in self.report["manualChecklist"].values()
        )
        self.report["completedAt"] = utc_now()
        write_json(self.report_dir / "real-package-report.json", self.report)

    def run(self) -> None:
        if not self.args.allow_user_settings_mutation:
            raise JourneyFailure("pass --allow-user-settings-mutation in a dedicated OS test account")
        if not port_is_free():
            raise JourneyFailure(f"{BRIDGE_HOST}:{BRIDGE_PORT} is already occupied before the test")
        if not is_within(self.package_root, self.work_dir.parent) and not self.args.allow_external_package:
            raise JourneyFailure("package root must be inside the test work area")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if self.args.artifact:
            artifact = canonical(self.args.artifact)
            self.report["artifact"] = {
                "path": str(artifact),
                "sha256": sha256(artifact),
                "size": artifact.stat().st_size,
            }
        self.check_package_shape()
        self.fake.start()
        self.prepare_external_root()
        if self.args.platform == "macos":
            self.app_snapshot = tree_snapshot(self.package_root)

        self.start_application("first-launch")
        self.wait_ready("first-launch", self.external_root)
        ready_shot = self.report_dir / "screenshots" / "ready.png"
        if capture_screenshot(ready_shot):
            self.screenshots.append(str(ready_shot))
        self.run_chat_upload_memory()

        self.stop_application()
        self.start_application("warm-restart")
        self.wait_ready("warm-restart", self.external_root)
        self.report["checks"]["warmRestart"] = True

        self.stop_application()
        self.run_port_conflict()
        self.relocate_package()
        self.stale_override_fallback()

        if self.args.platform == "macos" and self.app_snapshot is not None:
            after_snapshot = tree_snapshot(self.package_root)
            if after_snapshot != self.app_snapshot:
                changed = sorted(set(after_snapshot) ^ set(self.app_snapshot))
                changed += sorted(
                    key
                    for key in set(after_snapshot) & set(self.app_snapshot)
                    if after_snapshot[key] != self.app_snapshot[key]
                )
                raise JourneyFailure(f"first launch modified the signed .app: {changed[:20]}")
            self.report["checks"]["macAppImmutable"] = True

        if not self.args.screenshots_optional and len(self.screenshots) < 2:
            raise JourneyFailure("real-package journey did not capture ready and failure screenshots")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("windows", "linux", "macos"), required=True)
    parser.add_argument("--artifact", default="")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--application-relative", required=True)
    parser.add_argument("--runtime-relative", required=True)
    parser.add_argument("--relocated-root", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--start-timeout", type=float, default=300)
    parser.add_argument("--allow-user-settings-mutation", action="store_true")
    parser.add_argument("--allow-external-package", action="store_true")
    parser.add_argument("--screenshots-optional", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    journey = Journey(args)
    success = False
    try:
        journey.run()
        success = True
        return 0
    except BaseException as error:  # retain evidence for assertion and unexpected failures
        journey.report["failures"].append(f"{type(error).__name__}: {error}")
        print(f"real package journey failed: {error}", file=sys.stderr)
        return 1
    finally:
        with contextlib.suppress(BaseException):
            journey.cleanup()
        journey.save_report(success and journey.report["checks"].get("finalPortFree", False))
        print(journey.report_dir / "real-package-report.json")


if __name__ == "__main__":
    raise SystemExit(main())
