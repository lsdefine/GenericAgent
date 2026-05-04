#!/usr/bin/env python3
"""
AI-Powered Anomaly Detection for GenericAgent
基于统计规则与LLM辅助的异常检测模块
支持: 日志分析、指标阈值、事件模式识别、自动告警
"""

import os
import json
import time
import logging
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class AnomalyDetector:
    """异常检测器"""
    def __init__(self, config_file: str = "anomaly_config.json"):
        self.config_file = config_file
        self.metrics: Dict[str, deque] = {}
        self.alerts: List[Dict] = []
        self.rules = self._load_config()
        
    def _load_config(self):
        default_rules = {
            "cpu_usage": {"type": "threshold", "high": 90, "low": 5},
            "memory_mb": {"type": "threshold", "high": 1024},
            "error_rate": {"type": "threshold", "high": 0.1},
            "response_time_ms": {"type": "statistical", "zscore": 3.0},
            "task_duration_s": {"type": "statistical", "zscore": 2.5},
            "disk_usage_pct": {"type": "threshold", "high": 85}
        }
        if os.path.exists(self.config_file):
            with open(self.config_file) as f:
                return {**default_rules, **json.load(f)}
        return default_rules
    
    def _save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.rules, f, indent=2)
    
    def add_metric(self, name: str, value: float, max_samples: int = 1000):
        """添加指标数据点"""
        if name not in self.metrics:
            self.metrics[name] = deque(maxlen=max_samples)
        self.metrics[name].append({
            'value': value,
            'timestamp': time.time()
        })
    
    def check_anomalies(self) -> List[Dict]:
        """检查所有指标的异常"""
        new_alerts = []
        
        for metric_name, rule in self.rules.items():
            if metric_name not in self.metrics:
                continue
            
            values = [m['value'] for m in self.metrics[metric_name]]
            if len(values) < 3:
                continue
            
            latest = values[-1]
            
            if rule['type'] == 'threshold':
                if 'high' in rule and latest > rule['high']:
                    alert = {
                        'type': 'threshold_high',
                        'metric': metric_name,
                        'value': latest,
                        'threshold': rule['high'],
                        'timestamp': datetime.now().isoformat()
                    }
                    new_alerts.append(alert)
                if 'low' in rule and latest < rule['low']:
                    alert = {
                        'type': 'threshold_low',
                        'metric': metric_name,
                        'value': latest,
                        'threshold': rule['low'],
                        'timestamp': datetime.now().isoformat()
                    }
                    new_alerts.append(alert)
            
            elif rule['type'] == 'statistical':
                zscore_threshold = rule.get('zscore', 3.0)
                mean = statistics.mean(values[:-1])  # 排除最新值
                stdev = statistics.stdev(values[:-1]) if len(values) > 3 else 1
                
                if stdev > 0:
                    zscore = abs(latest - mean) / stdev
                    if zscore > zscore_threshold:
                        alert = {
                            'type': 'statistical_outlier',
                            'metric': metric_name,
                            'value': latest,
                            'mean': round(mean, 2),
                            'zscore': round(zscore, 2),
                            'timestamp': datetime.now().isoformat()
                        }
                        new_alerts.append(alert)
        
        self.alerts.extend(new_alerts)
        return new_alerts
    
    def analyze_logs(self, log_file: str = "app.log", window_minutes: int = 60) -> Dict:
        """分析日志文件中的异常模式"""
        if not os.path.exists(log_file):
            return {"error": "Log file not found"}
        
        cutoff = time.time() - (window_minutes * 60)
        patterns = {
            'errors': [],
            'warnings': [],
            'repeated_messages': {}
        }
        
        with open(log_file, 'r') as f:
            for line in f:
                line = line.strip()
                if '[ERROR]' in line.upper() or '[CRITICAL]' in line.upper():
                    patterns['errors'].append(line)
                elif '[WARNING]' in line.upper() or '[WARN]' in line.upper():
                    patterns['warnings'].append(line)
                
                # 检测重复消息
                msg_key = line.split(']')[-1].strip() if ']' in line else line
                if msg_key:
                    patterns['repeated_messages'][msg_key] = patterns['repeated_messages'].get(msg_key, 0) + 1
        
        # 过滤重复超过3次的消息
        patterns['repeated_messages'] = {
            k: v for k, v in patterns['repeated_messages'].items() if v >= 3
        }
        
        return {
            'analysis_time': datetime.now().isoformat(),
            'error_count': len(patterns['errors']),
            'warning_count': len(patterns['warnings']),
            'repeated_patterns': patterns['repeated_messages']
        }
    
    def get_alerts(self, limit: int = 50) -> List[Dict]:
        """获取最近的告警"""
        return self.alerts[-limit:]
    
    def clear_old_alerts(self, max_age_hours: int = 24):
        """清理旧告警"""
        cutoff = time.time() - (max_age_hours * 3600)
        self.alerts = [a for a in self.alerts if a.get('_timestamp', 0) > cutoff]
    
    def get_health_report(self) -> Dict:
        """生成健康报告"""
        anomalies = self.check_anomalies()
        return {
            'status': 'UNHEALTHY' if anomalies else 'HEALTHY',
            'active_anomalies': len(anomalies),
            'metrics_tracked': len(self.metrics),
            'total_alerts': len(self.alerts),
            'rules_count': len(self.rules),
            'recent_alerts': self.get_alerts(10)
        }

if __name__ == '__main__':
    detector = AnomalyDetector()
    
    # 模拟数据注入
    print("Injecting test metrics...")
    for i in range(20):
        detector.add_metric("response_time_ms", 100 + (i * 5))
    detector.add_metric("response_time_ms", 500)  # 异常值
    
    for i in range(10):
        detector.add_metric("cpu_usage", 40 + (i * 2))
    detector.add_metric("cpu_usage", 95)  # 超阈值
    
    print("\n=== Health Report ===")
    report = detector.get_health_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    
    print("\n=== Log Analysis ===")
    # 如果存在日志文件则分析
    if os.path.exists("app.log"):
        analysis = detector.analyze_logs("app.log")
        print(json.dumps(analysis, indent=2, ensure_ascii=False))
    else:
        print("No app.log found, skipping log analysis.")
