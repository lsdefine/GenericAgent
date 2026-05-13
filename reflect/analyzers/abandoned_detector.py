"""消失事项检测器 (原轴3/TrendDetector axis3 的语义化重构)

核心改动：
- 语义化命名: AbandonedDetector
- 输出只含统计信息（weeks_active, total_count, last_week, gap, pattern）
- 不含traceback_query，因为消失事项的下一步是对接L2记忆层比较，不需要回溯原始日志
- 基于 all_user_histories.txt（仅用户行）工作
- 复用HabitTracker的session解析+标注+矩阵逻辑，只改判定条件
"""
import sys, json, re, time, os
from collections import Counter, defaultdict

# 统一配置
try:
    from reflect.analyzers._config import PROJECT_ROOT, HIST_PATH, USER_HIST_PATH, get_llm_config, filter_user_histories
    from reflect.analyzers._json_utils import robust_json_parse
except (ImportError, ModuleNotFoundError):
    from _config import PROJECT_ROOT, HIST_PATH, USER_HIST_PATH, get_llm_config, filter_user_histories
    from _json_utils import robust_json_parse

from llmcore import LLMSession

# ============================================================
# 提示词 (与HabitTracker共用)
# ============================================================
TAG_PROMPT = """你是一个活动标注器。给定用户与AI助手的多个会话摘要，为每个会话标注1-3个活动标签。

## 规则
- 标签应描述用户主动发起的目标或项目（动词+宾语），如"开发truth_finder"、"学习GA机制"
- 只标注用户真正想做的事，忽略AI助手的中间执行步骤（如"搜索资料"、"读取文件"、"调试报错"等是手段不是目标）
- 如果会话内容不明确或太短，标注为"不明确"
- 每个会话独立标注

## 输出格式
JSON数组，每条: {"id": N, "tasks": ["标签1", "标签2"]}
只输出JSON。"""

NORMALIZE_PROMPT = """你是一个标签归一化器。给定一组活动标签（来自用户与AI助手的对话记录），请将含义相同或高度相关的标签合并为统一名称。

## 规则
- 同一件事的不同表述应合并为一个统一名称（选择最清晰简洁的表述）
- 例如："开发truth_finder功能"、"调试truth_finder"、"truth_finder优化" → 统一为 "开发truth_finder"
- 例如："记忆整合"、"记忆整理"、"执行记忆整理" → 统一为 "记忆整合"
- 如果某个标签独立存在、与其他标签无关，保持原样
- 不要强行合并无关标签

## 输出格式
JSON对象，key是原始标签，value是归一化后的统一名称:
{{"原标签A": "统一名称", "原标签B": "统一名称", "独立标签C": "独立标签C", ...}}

只输出JSON，不要其他内容。"""


class AbandonedDetector:
    """消失事项检测器 - 基于周x事项矩阵"""
    
    BATCH_SIZE = 40          # 每批送LLM标注的session数
    
    # 判定阈值
    MIN_WEEKS = 2            # 模式A: 最少出现周数
    MIN_GAP = 5              # 距今最少周数（须>=HabitTracker.RECENT_WINDOW避免逻辑矛盾）
    SINGLE_WEEK_MIN = 5      # 模式B: 单周最少出现次数（提高以过滤噪音）
    
    def __init__(self, hist_path=None, verbose=True):
        """
        Args:
            hist_path: 用户历史文件路径(应为过滤后的all_user_histories.txt)
            verbose: 是否打印进度
        """
        self.hist_path = hist_path or USER_HIST_PATH
        self.verbose = verbose
        self.sessions = []
        self.total_weeks = 0
        self.week_task_matrix = defaultdict(lambda: defaultdict(int))
        self.task_weeks = defaultdict(set)
    
    def _parse_sessions(self):
        """解析用户历史文件，提取sessions"""
        with open(self.hist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_session = None
        week_set = set()
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            
            if stripped.startswith("SESSION:"):
                if current_session:
                    self.sessions.append(current_session)
                
                session_name = stripped[8:].strip()
                week = self._calc_week(session_name)
                current_session = {
                    'name': session_name,
                    'week': week,
                    'user_lines': []
                }
                week_set.add(week)
                
            elif stripped.startswith("[USER]:") and current_session is not None:
                text = stripped[7:].strip()
                current_session['user_lines'].append(text)
        
        if current_session:
            self.sessions.append(current_session)
        
        self.total_weeks = max(week_set) if week_set else 0
        
        if self.verbose:
            print(f"[AbandonedDetector] 解析完成: {len(self.sessions)} sessions, {self.total_weeks} 周")
    
    def _calc_week(self, session_name):
        """从session名计算属于第几周"""
        try:
            start_part = session_name.split('-')[0]
            month = int(start_part[:2])
            day = int(start_part[2:4])
            day_of_year = (month - 1) * 30 + day
            return day_of_year // 7 + 1
        except (ValueError, IndexError):
            return 1
    
    def _call_llm(self, system_prompt, user_prompt):
        """调用LLM"""
        session = LLMSession(get_llm_config())
        session.system = system_prompt
        gen = session.ask(user_prompt)
        return ''.join(gen)
    
    def _extract_tasks_batch(self, batch_sessions):
        """批量提取session的活动标签"""
        batch_text = ""
        for i, s in enumerate(batch_sessions, 1):
            summary = " | ".join(s['user_lines'][:5])[:200]
            batch_text += f"[{i}] {s['name']}: {summary}\n"
        
        result = self._call_llm(TAG_PROMPT, f"以下是{len(batch_sessions)}个会话摘要：\n\n{batch_text}")
        
        # 鲁棒JSON解析
        items = robust_json_parse(result, expect_type="array")
        if items:
            for item in items:
                idx = item.get('id', 0) - 1
                if 0 <= idx < len(batch_sessions):
                    batch_sessions[idx]['tasks'] = item.get('tasks', [])
            return True
        return False
    
    def _tag_all_sessions(self):
        """批量标注所有session"""
        total_batches = (len(self.sessions) - 1) // self.BATCH_SIZE + 1
        
        for batch_idx in range(total_batches):
            start = batch_idx * self.BATCH_SIZE
            end = min(start + self.BATCH_SIZE, len(self.sessions))
            batch = self.sessions[start:end]
            
            success = self._extract_tasks_batch(batch)
            
            if self.verbose:
                tagged = sum(1 for s in batch if 'tasks' in s)
                status = "OK" if success else "FAIL"
                print(f"  Batch {batch_idx+1}/{total_batches}: {status} {tagged}/{len(batch)}")
            
            time.sleep(0.3)
        
        untagged = [s for s in self.sessions if 'tasks' not in s]
        if untagged and self.verbose:
            print(f"  重试 {len(untagged)} 未标注sessions...")
            self._extract_tasks_batch(untagged)
        
        tagged_count = sum(1 for s in self.sessions if 'tasks' in s)
        if self.verbose:
            print(f"  标注完成: {tagged_count}/{len(self.sessions)}")
    
    def _build_matrix(self):
        """构建周x事项矩阵，通过LLM自动归一化同义标签"""
        all_tasks = Counter()
        for s in self.sessions:
            for t in s.get('tasks', []):
                all_tasks[t] += 1
        
        # 纯LLM归一化：将所有出现>=2次的标签交给LLM聚类
        reverse_map = {}
        freq_tasks = [t for t, c in all_tasks.items() if c >= 2]
        
        if len(freq_tasks) >= 2:
            task_list = "\n".join(f"- {t} (出现{all_tasks[t]}次)" for t in freq_tasks)
            result = self._call_llm(NORMALIZE_PROMPT, f"标签列表:\n{task_list}")
            mappings = robust_json_parse(result, expect_type="object")
            if mappings:
                for orig, target in mappings.items():
                    if isinstance(target, str) and target.strip():
                        reverse_map[orig] = target.strip()
        
        self.week_task_matrix = defaultdict(lambda: defaultdict(int))
        self.task_weeks = defaultdict(set)
        
        for s in self.sessions:
            week = s['week']
            for t in s.get('tasks', []):
                unified = reverse_map.get(t, t)
                self.week_task_matrix[unified][week] += 1
                self.task_weeks[unified].add(week)
        
        if self.verbose:
            multi_week = sum(1 for ws in self.task_weeks.values() if len(ws) >= 2)
            print(f"[AbandonedDetector] 矩阵: {len(self.task_weeks)}事项, {multi_week}个跨>=2周")
    
    def detect(self, llm_client=None):
        """
        执行完整pipeline: 解析→标注→矩阵→判定
        
        Returns: [{
            "task": str,
            "weeks_active": [int],
            "total_count": int,
            "last_week": int,
            "gap": int,
            "pattern": "multi_week" | "single_burst"
        }]
        
        注意：不含traceback_query，因为消失事项的下一步是对接L2记忆层比较
        """
        # Phase 1: 解析sessions
        self._parse_sessions()
        
        # Phase 2-3: LLM标注
        self._tag_all_sessions()
        
        # Phase 4: 构建矩阵
        self._build_matrix()
        
        # Phase 5: 判定
        current_week = self.total_weeks
        abandoned = []
        
        for task, weeks in self.task_weeks.items():
            if task in ("不明确",):
                continue
            
            weeks_sorted = sorted(weeks)
            num_weeks = len(weeks_sorted)
            span = weeks_sorted[-1] - weeks_sorted[0] + 1
            last_week = weeks_sorted[-1]
            gap = current_week - last_week
            total_count = sum(self.week_task_matrix[task].values())
            
            # 模式A: 出现>=2周 + 距今>=3周
            is_pattern_a = (num_weeks >= self.MIN_WEEKS and gap >= self.MIN_GAP)
            # 模式B: 单周但>=3次 + 距今>=3周
            is_pattern_b = (num_weeks == 1 and total_count >= self.SINGLE_WEEK_MIN 
                          and gap >= self.MIN_GAP)
            
            if is_pattern_a or is_pattern_b:
                abandoned.append({
                    "task": task,
                    "weeks_active": weeks_sorted,
                    "total_count": total_count,
                    "last_week": last_week,
                    "gap": gap,
                    "pattern": "multi_week" if is_pattern_a else "single_burst"
                })
        
        # 排序
        abandoned.sort(key=lambda x: -x['total_count'])
        
        if self.verbose:
            print(f"\n[AbandonedDetector] 检出 {len(abandoned)} 个消失事项:")
            for item in abandoned[:15]:
                weeks_str = ",".join(f"W{w}" for w in item['weeks_active'])
                print(f"  \u2717 {item['task']}: {item['total_count']}次 ({weeks_str}) "
                      f"距今{item['gap']}周 [{item['pattern']}]")
        
        return abandoned
    
    def run(self, llm_client=None):
        """主入口，兼容旧接口"""
        return self.detect(llm_client)


# ============================================================
# CLI入口
# ============================================================
if __name__ == "__main__":
    # 确保用户历史文件存在
    filter_user_histories()
    
    detector = AbandonedDetector()
    results = detector.detect()
    
    # 保存结果
    output_path = os.path.join(os.path.dirname(__file__), "abandoned_results.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=list)
    print(f"\n结果已保存: {output_path}")
