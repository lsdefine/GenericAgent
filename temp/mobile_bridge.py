#!/usr/bin/env python3
"""
Cross-Platform Mobile Bridge for GenericAgent
跨平台移动桥接: 统一iOS/Android自动化接口
支持: ADB(Android)/Shortcuts(iOS)、消息推送、文件同步、远程执行
"""

import os
import json
import time
import logging
import subprocess
import platform
from datetime import datetime
from typing import Dict, List, Optional, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class MobileBridge:
    def __init__(self):
        self.devices: Dict[str, Dict] = {}
        self._detect_devices()
    
    def _detect_devices(self):
        """Detect connected mobile devices"""
        # Android via ADB
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines()[1:]:
                if line.strip() and 'device' in line:
                    serial = line.split()[0]
                    self.devices[serial] = {'type': 'android', 'status': 'connected'}
        except FileNotFoundError:
            logger.debug("ADB not found")
        
        # iOS via ideviceinfo (libimobiledevice)
        try:
            result = subprocess.run(['idevice_id', '-l'], capture_output=True, text=True, timeout=5)
            for udid in result.stdout.splitlines():
                if udid.strip():
                    self.devices[udid] = {'type': 'ios', 'status': 'connected'}
        except FileNotFoundError:
            logger.debug("libimobiledevice not found")
    
    def list_devices(self) -> List[Dict]:
        return [{'serial': k, **v} for k, v in self.devices.items()]
    
    # === Android (ADB) ===
    def adb_command(self, serial: str, cmd: str) -> Dict:
        full_cmd = ['adb', '-s', serial, 'shell', cmd]
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=30)
        return {'stdout': result.stdout, 'stderr': result.stderr, 'returncode': result.returncode}
    
    def adb_push(self, serial: str, local: str, remote: str) -> bool:
        result = subprocess.run(['adb', '-s', serial, 'push', local, remote], 
                               capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    
    def adb_pull(self, serial: str, remote: str, local: str) -> bool:
        result = subprocess.run(['adb', '-s', serial, 'pull', remote, local],
                               capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    
    def adb_tap(self, serial: str, x: int, y: int):
        return self.adb_command(serial, f'input tap {x} {y}')
    
    def adb_swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        return self.adb_command(serial, f'input swipe {x1} {y1} {x2} {y2} {duration}')
    
    def adb_text(self, serial: str, text: str):
        safe_text = text.replace(' ', '%s').replace("'", "\\'")
        return self.adb_command(serial, f'input text "{safe_text}"')
    
    def adb_screenshot(self, serial: str, output_path: str) -> bool:
        remote_path = '/sdcard/screenshot.png'
        self.adb_command(serial, f'screencap -p {remote_path}')
        return self.adb_pull(serial, remote_path, output_path)
    
    def adb_get_info(self, serial: str) -> Dict:
        info = {}
        for prop in ['ro.product.model', 'ro.build.version.release', 'ro.product.brand']:
            r = self.adb_command(serial, f'getprop {prop}')
            info[prop.split('.')[-1]] = r['stdout'].strip()
        return info
    
    # === iOS (Shortcuts URL scheme + AppleScript) ===
    def ios_run_shortcut(self, shortcut_name: str, input_data: Any = None) -> bool:
        url = f'shortcuts://run-shortcut?name={shortcut_name}'
        if input_data:
            url += f'&input={json.dumps(input_data)}'
        if platform.system() == 'Darwin':
            os.system(f'open "{url}"')
            return True
        return False
    
    def ios_applescript(self, script: str) -> Dict:
        if platform.system() != 'Darwin':
            return {'error': 'AppleScript requires macOS'}
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        return {'stdout': result.stdout, 'stderr': result.stderr, 'returncode': result.returncode}
    
    # === Push Notification ===
    def send_push(self, device_serial: str, title: str, message: str) -> bool:
        device = self.devices.get(device_serial)
        if not device:
            return False
        if device['type'] == 'android':
            return self._push_android(device_serial, title, message)
        else:
            return self._push_ios(device_serial, title, message)
    
    def _push_android(self, serial: str, title: str, message: str) -> bool:
        cmd = f'service call notification 1 s16 "{title}" s16 "{message}"'
        r = self.adb_command(serial, cmd)
        return r['returncode'] == 0
    
    def _push_ios(self, udid: str, title: str, message: str) -> bool:
        script = f'display notification "{message}" with title "{title}"'
        r = self.ios_applescript(script)
        return r.get('returncode', 1) == 0
    
    # === File Sync ===
    def sync_file(self, from_serial: str, from_path: str, to_serial: str, to_path: str) -> bool:
        local_tmp = f'/tmp/mobile_sync_{int(time.time())}'
        if self.adb_pull(from_serial, from_path, local_tmp):
            return self.adb_push(to_serial, local_tmp, to_path)
        return False

if __name__ == '__main__':
    bridge = MobileBridge()
    print("=== Connected Devices ===")
    print(json.dumps(bridge.list_devices(), indent=2))
    
    if not bridge.list_devices():
        print("\nNo physical devices detected (expected in dev environment)")
        print("Bridge ready for when devices are connected")
    
    print("\n=== Platform Info ===")
    print(f"Platform: {platform.system()}")
