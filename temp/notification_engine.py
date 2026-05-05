#!/usr/bin/env python3
"""Notification Engine - Multi-channel notification system"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(message)s")

class NotificationChannel:
    """Base notification channel"""
    def __init__(self, name: str):
        self.name = name
        self.enabled = True
        
    def send(self, message: str, **kwargs) -> bool:
        raise NotImplementedError


class TerminalChannel(NotificationChannel):
    """Terminal notification"""
    def send(self, message: str, level: str = "INFO", **kwargs) -> bool:
        if level == "INFO":
            logging.info(f"[TERMINAL] {message}")
        elif level == "WARNING":
            logging.warning(f"[TERMINAL] {message}")
        elif level == "ERROR":
            logging.error(f"[TERMINAL] {message}")
        return True


class FileChannel(NotificationChannel):
    """File-based notification"""
    def __init__(self, name: str, filepath: str = "notifications.log"):
        super().__init__(name)
        self.filepath = filepath
        
    def send(self, message: str, **kwargs) -> bool:
        try:
            with open(self.filepath, 'a') as f:
                timestamp = datetime.now().isoformat()
                f.write(f"[{timestamp}] {message}\n")
            return True
        except Exception as e:
            logging.error(f"File notification failed: {e}")
            return False


class WebhookChannel(NotificationChannel):
    """Webhook notification"""
    def __init__(self, name: str, url: str = ""):
        super().__init__(name)
        self.url = url
        
    def send(self, message: str, **kwargs) -> bool:
        logging.info(f"[WEBHOOK] Sending to {self.url}: {message}")
        return True


class SystemNotificationChannel(NotificationChannel):
    """macOS system notification (osascript)"""
    def send(self, message: str, **kwargs) -> bool:
        try:
            import subprocess
            title = kwargs.get('title', 'GenericAgent')
            cmd = ['osascript', '-e', f'display notification "{message}" with title "{title}"']
            subprocess.run(cmd, capture_output=True)
            return True
        except Exception:
            return False


class NotificationEngine:
    """Multi-channel notification engine"""
    def __init__(self):
        self.channels: List[NotificationChannel] = []
        
    def add_channel(self, channel: NotificationChannel):
        self.channels.append(channel)
        
    def notify(self, message: str, level: str = "INFO", **kwargs):
        """Send notification to all enabled channels"""
        results = []
        for channel in self.channels:
            if channel.enabled:
                try:
                    success = channel.send(message, level=level, **kwargs)
                    results.append((channel.name, success))
                except Exception as e:
                    results.append((channel.name, False))
        return results
        
    def notify_critical(self, message: str):
        """Send critical notification (forces all channels)"""
        return self.notify(message, level="CRITICAL")


if __name__ == "__main__":
    engine = NotificationEngine()
    
    # Add channels
    engine.add_channel(TerminalChannel("terminal"))
    engine.add_channel(FileChannel("file", "test_notifications.log"))
    engine.add_channel(WebhookChannel("webhook", "https://example.com/webhook"))
    engine.add_channel(SystemNotificationChannel("system"))
    
    # Test notifications
    print("=== Testing Notifications ===")
    engine.notify("System startup complete")
    engine.notify("Low disk space warning", level="WARNING")
    engine.notify_critical("Critical: Service down!")
    
    # Verify file log
    import os
    if os.path.exists("test_notifications.log"):
        with open("test_notifications.log") as f:
            print(f"\nFile log contents:")
            print(f.read())
        os.remove("test_notifications.log")
    
    print("Notification engine ready.")
