#!/usr/bin/env python3
"""
Webhook Trigger Templates for GenericAgent
预定义的Webhook触发模板，可快速注册到webhook_server
支持: GitHub/CI/Feishu/自定义事件 -> 任务映射
"""

import json
import os
import time
import logging
from typing import Dict, Any, Callable, Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 预定义Webhook模板库
WEBHOOK_TEMPLATES = {
    "github_push": {
        "name": "GitHub Push Event",
        "event_type": "git.push",
        "description": "当GitHub仓库有push事件时触发",
        "payload_schema": {
            "ref": "refs/heads/main",
            "repository": {"full_name": "owner/repo"},
            "commits": [{"id": "sha", "message": "msg"}]
        },
        "transform": lambda payload: {
            "task_type": "code_review",
            "repo": payload.get("repository", {}).get("full_name", ""),
            "branch": payload.get("ref", "").split("/")[-1],
            "commits": [c.get("message", "") for c in payload.get("commits", [])]
        },
        "enabled": True
    },
    "github_pr": {
        "name": "GitHub Pull Request",
        "event_type": "git.pr",
        "description": "当有PR创建/更新时触发",
        "payload_schema": {
            "action": "opened",
            "pull_request": {"number": 1, "title": "PR title"}
        },
        "transform": lambda payload: {
            "task_type": "pr_review",
            "action": payload.get("action", ""),
            "pr_number": payload.get("pull_request", {}).get("number", 0),
            "title": payload.get("pull_request", {}).get("title", "")
        },
        "enabled": True
    },
    "ci_complete": {
        "name": "CI/CD Pipeline Complete",
        "event_type": "ci.complete",
        "description": "CI/CD流水线完成时触发",
        "payload_schema": {
            "status": "success",
            "pipeline_id": "12345",
            "duration": 300
        },
        "transform": lambda payload: {
            "task_type": "deploy" if payload.get("status") == "success" else "notify_failure",
            "pipeline_id": payload.get("pipeline_id", ""),
            "status": payload.get("status", "unknown"),
            "duration": payload.get("duration", 0)
        },
        "enabled": True
    },
    "feishu_approval": {
        "name": "Feishu Approval",
        "event_type": "feishu.approval",
        "description": "飞书审批通过/拒绝时触发",
        "payload_schema": {
            "approval_id": "A001",
            "status": "approved",
            "approver": "user_id"
        },
        "transform": lambda payload: {
            "task_type": "process_approval",
            "approval_id": payload.get("approval_id", ""),
            "status": payload.get("status", ""),
            "approver": payload.get("approver", "")
        },
        "enabled": True
    },
    "monitoring_alert": {
        "name": "Monitoring Alert",
        "event_type": "monitor.alert",
        "description": "监控告警触发",
        "payload_schema": {
            "severity": "critical",
            "metric": "cpu_usage",
            "value": 95.5,
            "threshold": 90
        },
        "transform": lambda payload: {
            "task_type": "handle_alert",
            "severity": payload.get("severity", "info"),
            "metric": payload.get("metric", ""),
            "value": payload.get("value", 0),
            "threshold": payload.get("threshold", 0)
        },
        "enabled": True
    },
    "scheduled_backup": {
        "name": "Scheduled Backup",
        "event_type": "system.backup",
        "description": "定时备份触发",
        "payload_schema": {
            "backup_type": "full",
            "target": "database"
        },
        "transform": lambda payload: {
            "task_type": "execute_backup",
            "backup_type": payload.get("backup_type", "full"),
            "target": payload.get("target", "")
        },
        "enabled": True
    }
}

class WebhookTemplateManager:
    """Webhook模板管理器"""
    def __init__(self, config_file: str = "webhook_templates_config.json"):
        self.config_file = config_file
        self.active_templates: Dict[str, Dict] = {}
        self.custom_templates: Dict[str, Dict] = {}
        self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.active_templates = data.get("active", {})
                    self.custom_templates = data.get("custom", {})
                logger.info(f"Loaded webhook config: {len(self.active_templates)} active, {len(self.custom_templates)} custom")
            except Exception as e:
                logger.error(f"Failed to load webhook config: {e}")

    def _save_config(self):
        data = {
            "active": self.active_templates,
            "custom": self.custom_templates,
            "last_updated": datetime.now().isoformat()
        }
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_templates(self) -> Dict[str, Dict]:
        """列出所有可用模板"""
        return {**WEBHOOK_TEMPLATES, **self.custom_templates}

    def activate_template(self, template_name: str, custom_transform: Callable = None) -> bool:
        """激活一个模板"""
        if template_name in WEBHOOK_TEMPLATES:
            tpl = WEBHOOK_TEMPLATES[template_name].copy()
            if custom_transform:
                tpl["transform"] = custom_transform
            self.active_templates[template_name] = tpl
            self._save_config()
            logger.info(f"Activated template: {template_name}")
            return True
        elif template_name in self.custom_templates:
            self.active_templates[template_name] = self.custom_templates[template_name]
            self._save_config()
            logger.info(f"Activated custom template: {template_name}")
            return True
        logger.warning(f"Template not found: {template_name}")
        return False

    def deactivate_template(self, template_name: str):
        """停用模板"""
        if template_name in self.active_templates:
            del self.active_templates[template_name]
            self._save_config()
            logger.info(f"Deactivated template: {template_name}")

    def add_custom_template(self, name: str, event_type: str, transform: Callable, 
                           description: str = "", payload_schema: Dict = None):
        """添加自定义模板"""
        self.custom_templates[name] = {
            "name": name,
            "event_type": event_type,
            "description": description,
            "payload_schema": payload_schema or {},
            "transform": transform,
            "enabled": True
        }
        self._save_config()
        logger.info(f"Added custom template: {name}")

    def process_webhook(self, event_type: str, payload: Dict) -> Optional[Dict]:
        """处理Webhook请求，返回转换后的任务数据"""
        # 查找匹配的活跃模板
        for name, tpl in self.active_templates.items():
            if tpl.get("event_type") == event_type and tpl.get("enabled", True):
                try:
                    transform_func = tpl.get("transform")
                    if callable(transform_func):
                        task_data = transform_func(payload)
                        task_data["source_template"] = name
                        task_data["timestamp"] = datetime.now().isoformat()
                        logger.info(f"Webhook processed via template: {name}")
                        return task_data
                except Exception as e:
                    logger.error(f"Template transform error ({name}): {e}")
                    return None
        logger.warning(f"No active template for event: {event_type}")
        return None

    def get_webhook_server_config(self) -> Dict:
        """生成webhook_server.py可使用的配置"""
        routes = {}
        for name, tpl in self.active_templates.items():
            event_type = tpl.get("event_type", name)
            routes[f"/webhook/{event_type.replace('.', '/')}"] = {
                "method": "POST",
                "handler": "process_webhook",
                "template": name
            }
        return {"routes": routes, "templates": list(self.active_templates.keys())}


if __name__ == '__main__':
    # 演示用法
    manager = WebhookTemplateManager()
    
    print("=== Available Templates ===")
    for name, tpl in manager.list_templates().items():
        status = "✓" if name in manager.active_templates else " "
        print(f"  [{status}] {name}: {tpl['description']}")
    
    print("\n=== Activating Templates ===")
    manager.activate_template("github_push")
    manager.activate_template("ci_complete")
    manager.activate_template("monitoring_alert")
    
    print("\n=== Simulating Webhook ===")
    test_payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "loujohn/GenericAgent"},
        "commits": [{"id": "abc123", "message": "Fix bug"}]
    }
    result = manager.process_webhook("git.push", test_payload)
    print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
    
    print("\n=== Webhook Server Config ===")
    config = manager.get_webhook_server_config()
    print(json.dumps(config, indent=2, ensure_ascii=False))
