"""
统一扫描器 (Unified Scanner)
功能: 一次调用同时运行情绪扫描、习惯追踪、消失事项检测
设计: 增量扫描 + 状态持久化 + 定时任务集成

使用方式:
    # 作为模块调用
    from tri_axis_scanner import TriAxisScanner
    scanner = TriAxisScanner()
    report = scanner.run()
    
    # 命令行
    python tri_axis_scanner.py [--full]  # --full 强制全量扫描

输出: 扫描报告dict + 写入 scan_report.json

增量策略:
    情绪扫描: 记录上次扫描到的行号，只扫新增部分
    习惯/消失: 每次全量(基于周级矩阵，数据量可控)
    
定时频率建议: every_3d (每3天) 或 weekly
"""

import sys, os, json, time, traceback
from datetime import datetime

# 统一配置: 路径发现 + LLM配置 + 数据预处理 (兼容包导入和直接运行)
try:
    from reflect.analyzers._config import (
        PROJECT_ROOT, HIST_PATH, get_llm_config, ensure_histories, filter_user_histories
    )
except (ImportError, ModuleNotFoundError):
    from _config import PROJECT_ROOT, HIST_PATH, get_llm_config, ensure_histories, filter_user_histories

# ============================================================
# 配置
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "scan_state.json")
REPORT_FILE = os.path.join(BASE_DIR, "scan_report.json")

# 情绪扫描增量：每次最少扫描的新增行数阈值（低于此值跳过）
EMOTION_MIN_NEW_LINES = 200


class TriAxisScanner:
    """统一扫描调度器"""
    
    def __init__(self, verbose=True, force_full=False):
        self.verbose = verbose
        self.force_full = force_full
        self.state = self._load_state()
        self.report = {
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "emotion": None,
            "habits": None,
            "abandoned": None,
            "errors": [],
            "summary": ""
        }
    
    # ============================================================
    # 状态管理
    # ============================================================
    def _load_state(self):
        """加载上次扫描状态"""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "last_scan_time": None,
            "emotion_last_line": 0,
            "habits_last_scan": None,
            "scan_count": 0
        }
    
    def _save_state(self):
        """保存扫描状态"""
        self.state["last_scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state["scan_count"] = self.state.get("scan_count", 0) + 1
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
    
    # ============================================================
    # 情绪扫描 (增量)
    # ============================================================
    def _run_emotion(self):
        """运行情绪扫描，增量扫描新增行"""
        if self.verbose:
            print("\n" + "="*60)
            print("[情绪扫描] Emotion Scanner")
            print("="*60)
        
        # 使用用户历史文件
        user_hist = filter_user_histories()
        with open(user_hist, 'r', encoding='utf-8') as f:
            total_lines = sum(1 for _ in f)
        
        last_line = 0 if self.force_full else self.state.get("emotion_last_line", 0)
        new_lines = total_lines - last_line
        
        if new_lines < EMOTION_MIN_NEW_LINES and not self.force_full:
            msg = f"新增行数不足({new_lines}<{EMOTION_MIN_NEW_LINES})，跳过情绪扫描"
            if self.verbose:
                print(f"  ⏭️ {msg}")
            return {"skipped": True, "reason": msg, "new_lines": new_lines}
        
        if self.verbose:
            print(f"  扫描范围: L{last_line+1} ~ L{total_lines} ({new_lines}行)")
        
        try:
            from .emotion_scanner import EmotionScanner
        except ImportError:
            from emotion_scanner import EmotionScanner
        
        scanner = EmotionScanner(hist_path=user_hist, verbose=self.verbose)
        start_line = last_line + 1 if last_line > 0 else None
        results = scanner.run(start_line=start_line)
        
        # 更新状态
        self.state["emotion_last_line"] = total_lines
        
        # 精简报告
        emotion_report = {
            "scan_range": [last_line + 1, total_lines],
            "new_lines_scanned": new_lines,
            "tier1_clusters": len(results.get("tier1_clusters", [])),
            "tier2_isolated": len(results.get("tier2_isolated", [])),
            "stats": results.get("stats", {}),
            "top_clusters": results.get("tier1_clusters", [])[:5],
            "top_isolated": results.get("tier2_isolated", [])[:5],
        }
        
        if self.verbose:
            t1 = emotion_report["tier1_clusters"]
            t2 = emotion_report["tier2_isolated"]
            print(f"  [OK] 完成: {t1}个波动区 + {t2}个孤立高强度点")
        
        return emotion_report
    
    # ============================================================
    # 习惯追踪 (全量)
    # ============================================================
    def _run_habits(self):
        """运行习惯追踪，全量扫描"""
        if self.verbose:
            print("\n" + "="*60)
            print("[习惯追踪] Habit Tracker")
            print("="*60)
        
        user_hist = filter_user_histories()
        
        try:
            from .habit_tracker import HabitTracker
        except ImportError:
            from habit_tracker import HabitTracker
        
        tracker = HabitTracker(hist_path=user_hist, verbose=self.verbose)
        results = tracker.detect()
        
        # 更新状态
        self.state["habits_last_scan"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        habits_report = {
            "count": len(results),
            "items": [{
                "task": item["task"],
                "weeks_active": item["weeks_active"],
                "total_count": item["total_count"],
                "span": item["span"],
                "source_lines_count": len(item.get("source_lines", []))
            } for item in results]
        }
        
        if self.verbose:
            print(f"  [OK] 习惯追踪: {habits_report['count']}项持续活跃")
            for item in results[:5]:
                print(f"     ★ {item['task']} ({item['total_count']}次, span={item['span']}周)")
        
        return habits_report
    
    # ============================================================
    # 消失事项检测 (全量)
    # ============================================================
    def _run_abandoned(self):
        """运行消失事项检测，全量扫描"""
        if self.verbose:
            print("\n" + "="*60)
            print("[消失检测] Abandoned Detector")
            print("="*60)
        
        user_hist = filter_user_histories()
        
        try:
            from .abandoned_detector import AbandonedDetector
        except ImportError:
            from abandoned_detector import AbandonedDetector
        
        detector = AbandonedDetector(hist_path=user_hist, verbose=self.verbose)
        results = detector.detect()
        
        abandoned_report = {
            "count": len(results),
            "items": [{
                "task": item["task"],
                "weeks_active": item["weeks_active"],
                "total_count": item["total_count"],
                "last_week": item["last_week"],
                "gap": item["gap"]
            } for item in results[:20]]
        }
        
        if self.verbose:
            print(f"  [OK] 消失检测: {abandoned_report['count']}项已消失")
            for item in results[:5]:
                print(f"     ✗ {item['task']} ({item['total_count']}次, gap={item['gap']}周)")
        
        return abandoned_report
    
    # ============================================================
    # 主入口
    # ============================================================
    def run(self):
        """运行统一扫描，返回完整报告"""
        # 确保 all_histories.txt 存在
        ensure_histories()
        
        start_time = time.time()
        
        if self.verbose:
            print("╔══════════════════════════════════════════════════════════╗")
            print("║            统一扫描器 (Unified Scanner)                 ║")
            print("╠══════════════════════════════════════════════════════════╣")
            mode = "全量" if self.force_full else "增量"
            print(f"║  模式: {mode}  |  第{self.state.get('scan_count',0)+1}次扫描")
            print(f"║  时间: {self.report['scan_time']}")
            print("╚══════════════════════════════════════════════════════════╝")
        
        # --- 情绪扫描 ---
        try:
            self.report["emotion"] = self._run_emotion()
        except Exception as e:
            err = f"情绪扫描异常: {e}\n{traceback.format_exc()}"
            self.report["errors"].append(err)
            self.report["emotion"] = {"error": str(e)}
            if self.verbose:
                print(f"  [X] 情绪扫描失败: {e}")
        
        # --- 习惯追踪 ---
        try:
            self.report["habits"] = self._run_habits()
        except Exception as e:
            err = f"习惯追踪异常: {e}\n{traceback.format_exc()}"
            self.report["errors"].append(err)
            self.report["habits"] = {"error": str(e)}
            if self.verbose:
                print(f"  [X] 习惯追踪失败: {e}")
        
        # --- 消失检测 ---
        try:
            self.report["abandoned"] = self._run_abandoned()
        except Exception as e:
            err = f"消失检测异常: {e}\n{traceback.format_exc()}"
            self.report["errors"].append(err)
            self.report["abandoned"] = {"error": str(e)}
            if self.verbose:
                print(f"  [X] 消失检测失败: {e}")
        
        # --- 汇总 ---
        elapsed = time.time() - start_time
        self.report["elapsed_seconds"] = round(elapsed, 1)
        self.report["summary"] = self._build_summary()
        
        # 保存报告和状态
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, ensure_ascii=False, indent=2)
        self._save_state()
        
        if self.verbose:
            print(f"\n{'='*60}")
            print(f"扫描完成 ({elapsed:.1f}s)")
            print(f"报告: {REPORT_FILE}")
            print(f"{'='*60}")
            print(f"\n{self.report['summary']}")
        
        return self.report
    
    def _build_summary(self):
        """生成人类可读的摘要"""
        lines = []
        
        # 情绪
        emo = self.report.get("emotion", {})
        if emo.get("skipped"):
            lines.append(f"情绪: 跳过({emo.get('reason','')})")
        elif emo.get("error"):
            lines.append(f"情绪: 错误 - {emo['error']}")
        else:
            t1 = emo.get("tier1_clusters", 0)
            t2 = emo.get("tier2_isolated", 0)
            lines.append(f"情绪: {t1}个波动区 + {t2}个高强度点")
        
        # 习惯
        hab = self.report.get("habits", {})
        if hab.get("error"):
            lines.append(f"习惯: 错误 - {hab['error']}")
        else:
            count = hab.get("count", 0)
            names = [item["task"] for item in hab.get("items", [])[:3]]
            lines.append(f"习惯: {count}项 [{', '.join(names)}]")
        
        # 消失
        abd = self.report.get("abandoned", {})
        if abd.get("error"):
            lines.append(f"消失: 错误 - {abd['error']}")
        else:
            count = abd.get("count", 0)
            names = [item["task"] for item in abd.get("items", [])[:3]]
            lines.append(f"消失: {count}项 [{', '.join(names)}]")
        
        return " | ".join(lines)


# ============================================================
# CLI入口
# ============================================================
if __name__ == "__main__":
    force = "--full" in sys.argv
    scanner = TriAxisScanner(verbose=True, force_full=force)
    report = scanner.run()
