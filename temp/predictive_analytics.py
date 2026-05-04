#!/usr/bin/env python3
"""
Predictive Analytics Module for GenericAgent
预测分析: 基于历史数据的趋势预测、异常预判、容量规划
支持: 线性回归、移动平均、季节性分解、预测可视化
纯Python实现, 无外部依赖
"""

import os
import json
import math
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class PredictiveAnalytics:
    def __init__(self, data_file: str = "analytics_data.json"):
        self.data_file = data_file
        self.datasets: Dict[str, List[Dict]] = {}
        self.models: Dict[str, Dict] = {}
        self._load_data()
    
    def _load_data(self):
        if os.path.exists(self.data_file):
            with open(self.data_file) as f:
                self.datasets = json.load(f)
    
    def _save_data(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.datasets, f, indent=2)
    
    def add_datapoint(self, dataset: str, timestamp: str, value: float, metadata: Dict = None):
        if dataset not in self.datasets:
            self.datasets[dataset] = []
        self.datasets[dataset].append({
            'timestamp': timestamp, 'value': value, 'metadata': metadata or {}
        })
        self.datasets[dataset].sort(key=lambda x: x['timestamp'])
        self._save_data()
    
    def get_series(self, dataset: str, last_n: int = None) -> List[Tuple[str, float]]:
        data = self.datasets.get(dataset, [])
        if last_n:
            data = data[-last_n:]
        return [(d['timestamp'], d['value']) for d in data]
    
    def moving_average(self, dataset: str, window: int = 7) -> List[float]:
        series = self.get_series(dataset)
        values = [v for _, v in series]
        if len(values) < window:
            return values
        result = []
        for i in range(len(values) - window + 1):
            result.append(sum(values[i:i+window]) / window)
        return result
    
    def linear_regression(self, dataset: str, forecast_steps: int = 5) -> Dict:
        series = self.get_series(dataset)
        n = len(series)
        if n < 2:
            return {'error': 'Need at least 2 points'}
        
        x_vals = list(range(n))
        y_vals = [v for _, v in series]
        
        x_mean = sum(x_vals) / n
        y_mean = sum(y_vals) / n
        
        ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        ss_xx = sum((x - x_mean) ** 2 for x in x_vals)
        
        if ss_xx == 0:
            return {'slope': 0, 'intercept': y_mean, 'forecast': [], 'r_squared': 0}
        
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        
        # R-squared
        y_pred = [slope * x + intercept for x in x_vals]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(y_vals, y_pred))
        ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Forecast
        forecast = []
        for i in range(1, forecast_steps + 1):
            forecast.append({'step': i, 'value': round(slope * (n - 1 + i) + intercept, 2)})
        
        return {
            'slope': round(slope, 4), 'intercept': round(intercept, 2),
            'r_squared': round(r_squared, 4), 'forecast': forecast,
            'trend': 'increasing' if slope > 0.01 else ('decreasing' if slope < -0.01 else 'stable')
        }
    
    def exponential_smoothing(self, dataset: str, alpha: float = 0.3, forecast_steps: int = 5) -> Dict:
        series = self.get_series(dataset)
        values = [v for _, v in series]
        if not values:
            return {'error': 'No data'}
        
        s = [values[0]]
        for i in range(1, len(values)):
            s.append(alpha * values[i] + (1 - alpha) * s[-1])
        
        forecast = [round(s[-1], 2)]
        for _ in range(1, forecast_steps):
            forecast.append(round(forecast[-1], 2))
        
        mae = sum(abs(v - pred) for v, pred in zip(values[1:], s[1:])) / max(len(values) - 1, 1)
        
        return {
            'smoothed': [round(x, 2) for x in s[-5:]],
            'forecast': forecast, 'mae': round(mae, 2)
        }
    
    def detect_trend_change(self, dataset: str, window: int = 10) -> Dict:
        series = self.get_series(dataset)
        values = [v for _, v in series]
        if len(values) < window * 2:
            return {'error': 'Insufficient data'}
        
        recent = values[-window:]
        previous = values[-2*window:-window]
        
        recent_avg = sum(recent) / window
        previous_avg = sum(previous) / window
        
        change_pct = (recent_avg - previous_avg) / previous_avg * 100 if previous_avg != 0 else 0
        
        return {
            'previous_avg': round(previous_avg, 2),
            'recent_avg': round(recent_avg, 2),
            'change_pct': round(change_pct, 2),
            'direction': 'up' if change_pct > 5 else ('down' if change_pct < -5 else 'stable')
        }
    
    def generate_report(self, dataset: str) -> Dict:
        lr = self.linear_regression(dataset)
        es = self.exponential_smoothing(dataset)
        tc = self.detect_trend_change(dataset)
        
        return {
            'dataset': dataset, 'datapoints': len(self.get_series(dataset)),
            'linear_regression': lr, 'exponential_smoothing': es,
            'trend_change': tc, 'generated_at': datetime.now().isoformat()
        }

if __name__ == '__main__':
    analytics = PredictiveAnalytics()
    
    import random
    now = datetime.now()
    for i in range(30):
        ts = (now - timedelta(days=30-i)).isoformat()
        val = 100 + i * 2 + random.gauss(0, 5)
        analytics.add_datapoint("cpu_usage", ts, round(val, 1))
    
    print("=== Linear Regression ===")
    print(json.dumps(analytics.linear_regression("cpu_usage", forecast_steps=5), indent=2))
    
    print("\n=== Trend Change ===")
    print(json.dumps(analytics.detect_trend_change("cpu_usage"), indent=2))
    
    print("\n=== Full Report ===")
    print(json.dumps(analytics.generate_report("cpu_usage"), indent=2))
