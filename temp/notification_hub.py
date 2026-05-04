#!/usr/bin/env python3
"""
Multi-Channel Notification Hub for GenericAgent
多渠道通知中心: 集成邮件/Slack/飞书/终端/文件等多种通知渠道
支持: 路由规则、优先级、去重、批量、模板
"""

import os
import json
import time
import hashlib
import logging
import smtplib
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Any, Optional, Callable
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class NotificationChannel:
    """通知渠道基类"""
    def send(self, notification: Dict) -> bool:
        raise NotImplementedError

class TerminalChannel(NotificationChannel):
    """终端输出"""
    def send(self, notification: Dict) -> bool:
        levels = {'low': '\033[94m', 'medium': '\033[93m', 'high': '\033[91m', 'critical': '\033[41m'}
        color = levels.get(notification.get('priority', 'low'), '\033[0m')
        reset = '\033[0m'
        print(f"{color}[{notification.get('priority', 'low').upper()}] {notification.get('title', '')}: {notification.get('body', '')}{reset}")
        return True

class FileChannel(NotificationChannel):
    """文件写入"""
    def __init__(self, path: str = "notifications.log"):
        self.path = path
    
    def send(self, notification: Dict) -> bool:
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(f"{json.dumps(notification, ensure_ascii=False)}\n")
            return True
        except Exception as e:
            logger.error(f"File channel error: {e}")
            return False

class WebhookChannel(NotificationChannel):
    """Webhook (飞书/Slack等)"""
    def __init__(self, url: str, platform: str = "generic"):
        self.url = url
        self.platform = platform
    
    def send(self, notification: Dict) -> bool:
        try:
            if self.platform == "feishu":
                payload = {
                    "msg_type": "text",
                    "content": {"text": f"[{notification.get('priority', 'info').upper()}] {notification.get('title', '')}\n{notification.get('body', '')}"}
                }
            elif self.platform == "slack":
                payload = {
                    "text": f"*[{notification.get('priority', 'info').upper()}] {notification.get('title', '')}*\n{notification.get('body', '')}"
                }
            else:
                payload = notification
            
            resp = requests.post(self.url, json=payload, timeout=10)
            return resp.status_code < 300
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return False

class EmailChannel(NotificationChannel):
    """邮件通知"""
    def __init__(self, smtp_host: str, smtp_port: int, user: str, password: str, to_email: str):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.user = user
        self.password = password
        self.to_email = to_email
    
    def send(self, notification: Dict) -> bool:
        try:
            msg = MIMEMultipart()
            msg['From'] = self.user
            msg['To'] = self.to_email
            msg['Subject'] = f"[{notification.get('priority', 'info').upper()}] {notification.get('title', '')}"
            msg.attach(MIMEText(notification.get('body', ''), 'plain', 'utf-8'))
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.error(f"Email error: {e}")
            return False

class NotificationHub:
    """通知中心"""
    def __init__(self, config_file: str = "notification_config.json"):
        self.channels: Dict[str, NotificationChannel] = {}
        self.sent_history = deque(maxlen=1000)
        self.dedup_window = 300  # 5分钟去重
        self.config_file = config_file
        self._load_config()
        # 默认注册终端和文件渠道
        if not self.channels:
            self.register_channel('terminal', TerminalChannel())
            self.register_channel('file', FileChannel())
    
    def _load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file) as f:
                config = json.load(f)
            for ch_name, ch_config in config.get('channels', {}).items():
                self._register_from_config(ch_name, ch_config)
    
    def _register_from_config(self, name: str, config: Dict):
        ch_type = config.get('type')
        if ch_type == 'webhook':
            self.register_channel(name, WebhookChannel(config['url'], config.get('platform', 'generic')))
        elif ch_type == 'email':
            self.register_channel(name, EmailChannel(config['smtp_host'], config['smtp_port'], config['user'], config['password'], config['to']))
        elif ch_type == 'file':
            self.register_channel(name, FileChannel(config.get('path', 'notifications.log')))
    
    def register_channel(self, name: str, channel: NotificationChannel):
        self.channels[name] = channel
    
    def _dedup_key(self, notification: Dict) -> str:
        content = f"{notification.get('title', '')}{notification.get('body', '')}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def is_duplicate(self, notification: Dict) -> bool:
        key = self._dedup_key(notification)
        now = time.time()
        for item in self.sent_history:
            if item['key'] == key and now - item['time'] < self.dedup_window:
                return True
        return False
    
    def notify(self, title: str, body: str, priority: str = "medium", channels: List[str] = None) -> Dict:
        notification = {
            'title': title,
            'body': body,
            'priority': priority,
            'timestamp': datetime.now().isoformat(),
            'id': str(int(time.time()))
        }
        
        if self.is_duplicate(notification):
            return {'status': 'skipped', 'reason': 'duplicate'}
        
        target_channels = channels or list(self.channels.keys())
        results = {}
        
        for ch_name in target_channels:
            if ch_name in self.channels:
                try:
                    success = self.channels[ch_name].send(notification)
                    results[ch_name] = 'sent' if success else 'failed'
                except Exception as e:
                    results[ch_name] = f'error: {e}'
        
        self.sent_history.append({'key': self._dedup_key(notification), 'time': time.time()})
        return {'status': 'completed', 'results': results, 'notification': notification}
    
    def notify_batch(self, notifications: List[Dict]) -> List[Dict]:
        results = []
        for n in notifications:
            result = self.notify(
                n.get('title', ''),
                n.get('body', ''),
                n.get('priority', 'medium'),
                n.get('channels')
            )
            results.append(result)
        return results
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        return list(self.sent_history)[-limit:]

if __name__ == '__main__':
    hub = NotificationHub()
    
    print("=== Testing Notifications ===")
    
    # Low priority
    r1 = hub.notify("Test", "Low priority test message", "low")
    print(f"Low: {r1['status']}")
    
    # High priority
    r2 = hub.notify("Alert", "High priority alert!", "high")
    print(f"High: {r2['status']}")
    
    # Duplicate test
    r3 = hub.notify("Alert", "High priority alert!", "high")
    print(f"Duplicate: {r3['status']}")
    
    print("\n=== History ===")
    print(json.dumps(hub.get_history(), indent=2, ensure_ascii=False))
