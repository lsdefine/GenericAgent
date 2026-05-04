#!/usr/bin/env python3
"""
shortcut_bridge.py - Standardized bridge for macOS Shortcuts CLI execution.
Discovered Assets (from shortcut_discovery.py): 19 Shortcuts
"""
import subprocess
import json
import time
from pathlib import Path

class ShortcutBridge:
    def __init__(self, timeout=60):
        self.timeout = timeout
        self.available = self._discover()

    def _discover(self):
        """Fetch available shortcuts via CLI."""
        try:
            result = subprocess.run(['shortcuts', 'list'], 
                                    capture_output=True, text=True, timeout=10)
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception as e:
            return [f"Error: {e}"]

    def run(self, shortcut_name: str, input_path: str = None, output_file: str = None):
        """Execute a specific shortcut."""
        if shortcut_name not in self.available:
            return {"status": "error", "msg": f"Shortcut '{shortcut_name}' not found."}

        cmd = ['shortcuts', 'run', shortcut_name]
        if input_path:
            cmd.extend(['--input-file', input_path])
        
        start_time = time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            duration = time.time() - start_time
            return {
                "status": "success" if result.returncode == 0 else "error",
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": round(duration, 2)
            }
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "duration": self.timeout}

    def list_shortcuts(self):
        return self.available

if __name__ == '__main__':
    bridge = ShortcutBridge()
    print(f"Available Shortcuts ({len(bridge.available)}):")
    for s in bridge.available:
        print(f"  - {s}")
    
    # Demo usage
    # res = bridge.run("iPhone 屏幕截图")
    # print(json.dumps(res, indent=2))