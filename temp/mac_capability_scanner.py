#!/usr/bin/env python3
"""macOS System Capabilities Scanner"""
import platform, subprocess, logging, os
logging.basicConfig(level=logging.INFO)

class MacCapabilityScanner:
    def __init__(self):
        self.capabilities = {}

    def scan_all(self):
        self._scan_system_info()
        self._scan_hardware()
        self._scan_services()
        self._scan_automation_apis()
        self._scan_security()
        return self.capabilities

    def _scan_system_info(self):
        self.capabilities["system"] = {
            "macos_version": platform.mac_ver()[0],
            "python_version": platform.python_version(),
            "arch": platform.machine(),
            "hostname": platform.node()
        }

    def _scan_hardware(self):
        try:
            r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
            mem_gb = int(r.stdout.strip()) / (1024**3)
            self.capabilities["hardware"] = {
                "memory_gb": round(mem_gb, 1),
                "cpu_count": os.cpu_count()
            }
        except:
            self.capabilities["hardware"] = {}

    def _scan_services(self):
        services = ["ssh", "screen_sharing", "airdrop"]
        for svc in services:
            try:
                r = subprocess.run(["launchctl", "list", f"com.apple.{svc}"], capture_output=True, text=True)
                self.capabilities.setdefault("services", {})[svc] = r.returncode == 0
            except:
                pass

    def _scan_automation_apis(self):
        apis = {
            "applescript": "osascript -e \"return true\"",
            "automator": "which Automator",
            "shortcuts": "shortcuts --help"
        }
        for name, cmd in apis.items():
            try:
                r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=3)
                self.capabilities.setdefault("automation", {})[name] = r.returncode == 0
            except:
                pass

    def _scan_security(self):
        try:
            r = subprocess.run(["security", "find-generic-password", "-s", "test"], capture_output=True, text=True)
            self.capabilities["security"] = {
                "keychain_available": True,
                "sip_status": "unknown"
            }
        except:
            self.capabilities["security"] = {}

if __name__ == "__main__":
    scanner = MacCapabilityScanner()
    caps = scanner.scan_all()
    logging.info(f"macOS Capabilities: {caps}")
