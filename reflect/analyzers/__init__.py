"""
reflect/analyzers - 历史分析模块包

语义化命名:
- EmotionScanner: 情绪波动检测（原轴1）
- HabitTracker: 持续活跃模式检测（原轴2）
- AbandonedDetector: 已消失事项检测（原轴3）
- TriAxisScanner: 统一调度器

兼容旧名:
- EmotionDetector → EmotionScanner
- TrendDetector (保留)
"""
from .emotion_scanner import EmotionScanner
from .habit_tracker import HabitTracker
from .abandoned_detector import AbandonedDetector
from .tri_axis_scanner import TriAxisScanner

# 兼容旧名
EmotionDetector = EmotionScanner
