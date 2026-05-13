"""高频习惯追踪器 (原轴2/TrendDetector axis2 的语义化重构)

核心改动：
- 语义化命名: HabitTracker
- 输出增加 source_lines 字段: 每个task对应的原始USER行文本列表
  source_lines[i]['text'] 可直接传给 session_traceback.traceback() 溯源
- 基于 all_user_histories.txt（仅用户行）工作
- 保留完整LLM批处理+周矩阵+归一化逻辑
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
# 提示词
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


class HabitTracker:
    """高频习惯追踪器 - 基于周x事项矩阵 + 溯源"""
    
    BATCH_SIZE = 40          # 每批送LLM标注的session数
    
    # 判定阈值 (放宽版, 经602 sessions验证)
    MIN_WEEKS = 2            # 最少出现周数
    MIN_SPAN = 2             # 最少跨越周数
    RECENT_WINDOW = 5        # 最近N周内有出现才算活跃（放宽以覆盖间歇性习惯）
    
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
        # 存储每个session的原始USER行，用于溯源
        self._session_user_lines = {}  # session_name -> [user_line_text, ...]
    
    def _parse_sessions(self):
        """解析用户历史文件，提取sessions和对应的USER行"""
        with open(self.hist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        current_session = None
        current_lines = []
        week_set = set()
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            
            if stripped.startswith("SESSION:"):
                # 保存上一个session
                if current_session:
                    self.sessions.append(current_session)
                    self._session_user_lines[current_session['name']] = current_lines
                
                # 解析新session
                session_name = stripped[8:].strip()
                # 从session名提取周信息 (格式: MMDD_HHMM-MMDD_HHMM)
                week = self._calc_week(session_name)
                current_session = {
                    'name': session_name,
                    'week': week,
                    'user_lines': []
                }
                current_lines = []
                week_set.add(week)
                
            elif stripped.startswith("[USER]:") and current_session is not None:
                text = stripped[7:].strip()
                current_session['user_lines'].append(text)
                current_lines.append(text)
        
        # 最后一个session
        if current_session:
            self.sessions.append(current_session)
            self._session_user_lines[current_session['name']] = current_lines
        
        self.total_weeks = max(week_set) if week_set else 0
        
        if self.verbose:
            print(f"[HabitTracker] 解析完成: {len(self.sessions)} sessions, {self.total_weeks} 周")
    
    def _calc_week(self, session_name):
        """从session名计算属于第几周（简化：按月日推算）"""
        try:
            # 格式: MMDD_HHMM-MMDD_HHMM
            start_part = session_name.split('-')[0]
            month = int(start_part[:2])
            day = int(start_part[2:4])
            # 简化周计算：以1月1日为基准
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
        
        # 重试未标注的
        untagged = [s for s in self.sessions if 'tasks' not in s]
        if untagged and self.verbose:
            print(f"  重试 {len(untagged)} 未标注sessions...")
            self._extract_tasks_batch(untagged)
        
        tagged_count = sum(1 for s in self.sessions if 'tasks' in s)
        if self.verbose:
            print(f"  标注完成: {tagged_count}/{len(self.sessions)}")
    
    def _build_matrix(self):
        """构建周x事项矩阵，通过LLM自动归一化同义标签"""
        # 统计所有标签
        all_tasks = Counter()
        for s in self.sessions:
            for t in s.get('tasks', []):
                all_tasks[t] += 1
        
        # 纯LLM归一化：将所有出现>=2次的标签交给LLM聚类
        reverse_map = {}
        freq_tasks = [t for t, c in all_tasks.items() if c >= 2]
        
        if len(freq_tasks) >= 2:
            # 让LLM自主发现同义标签并合并
            task_list = "\n".join(f"- {t} (出现{all_tasks[t]}次)" for t in freq_tasks)
            result = self._call_llm(NORMALIZE_PROMPT, f"标签列表:\n{task_list}")
            mappings = robust_json_parse(result, expect_type="object")
            if mappings:
                for orig, target in mappings.items():
                    if isinstance(target, str) and target.strip():
                        reverse_map[orig] = target.strip()
        
        # 构建矩阵
        self.week_task_matrix = defaultdict(lambda: defaultdict(int))
        self.task_weeks = defaultdict(set)
        
        for s in self.sessions:
            week = s['week']
            for t in s.get('tasks', []):
                unified = reverse_map.get(t, t)
                self.week_task_matrix[unified][week] += 1
                self.task_weeks[unified].add(week)
        
        # 存储reverse_map供溯源使用
        self._reverse_map = reverse_map
        
        if self.verbose:
            multi_week = sum(1 for ws in self.task_weeks.values() if len(ws) >= 2)
            print(f"[HabitTracker] 矩阵: {len(self.task_weeks)}事项, {multi_week}个跨>=2周")
    
    def _collect_source_lines(self, task, sessions, max_per_session=3, max_total=15):
        """收集某个task对应的代表性USER行文本（用于溯源）
        
        策略: 
        1. 从session中找所有含task关键词的行
        2. 如果找到，取第一个匹配行作为锚点（最能代表用户发起该任务的时刻）
        3. 如果整个session都没匹配（可能LLM从语义而非关键词判断），fallback取line[0]
        
        这样在多任务session中，不会把属于任务A的首行错误归到任务B
        
        Args:
            task: 归一化后的任务名
            sessions: 包含该task的session列表
            max_per_session: 每个session最多取几行
            max_total: 总共最多取几行
            
        Returns:
            [{"text": "用户原话", "session": "session_name"}, ...]
        """
        # === 关键词提取 ===
        # 步骤: 分隔符拆 → 中英文边界拆 → 停用词过滤 → 中文bigram扩展
        # 停用词: 高频无区分度的通用词，过滤后提升匹配精度
        _STOPWORDS = {'项目', '功能', '内容', '方案', '工具', '系统', '文件', '代码',
                      '问题', '东西', '了解', '学习', '研究', '调研', '查看', '检查',
                      '测试', '使用', '配置', '设计', '开发', '优化', '分析', '处理',
                      '实现', '运行', '执行', '操作', '帮我', '一下', '一个', '什么',
                      '怎么', '这个', '那个', '可以', '需要', '进行'}
        
        # 子进程消息模式 (agent内部调度产生的，非用户真实输入)
        _SUBPROCESS_PATTERNS = [
            r'^SOP:', r'^你是.{0,30}子任务执行者',
            r'^你是DeepResearch', r'^\[System\]',
            r'^## 任务', r'^Phase\d+',
        ]
        
        parts = re.split(r'[/\s\-_，。、]', task)
        keywords = []
        for part in parts:
            sub_parts = re.split(r'(?<=[a-zA-Z0-9])(?=[\u4e00-\u9fff])|(?<=[\u4e00-\u9fff])(?=[a-zA-Z0-9])', part)
            for w in sub_parts:
                if re.match(r'^[a-zA-Z0-9]+$', w):
                    if len(w) >= 1:
                        keywords.append(w)
                elif len(w) >= 2:
                    keywords.append(w)
        
        # 过滤停用词
        keywords = [kw for kw in keywords if kw not in _STOPWORDS]
        
        # 中文长词(>2字)展开为bigram，增加部分匹配能力
        # 例: "新趋势" → ["新趋势", "新趋", "趋势"]
        expanded = []
        for kw in keywords:
            expanded.append(kw)
            if not re.match(r'^[a-zA-Z0-9]+$', kw) and len(kw) > 2:
                for i in range(len(kw) - 1):
                    bigram = kw[i:i+2]
                    if bigram not in expanded:
                        expanded.append(bigram)
        keywords = expanded
        
        # 去重(保序)
        seen = set()
        unique_kws = []
        for kw in keywords:
            kl = kw.lower()
            if kl not in seen:
                seen.add(kl)
                unique_kws.append(kw)
        keywords = unique_kws
        
        # 匹配阈值: 至少命中2个关键词才算精确匹配
        # 若关键词总数不足2，则要求全部命中
        min_match = min(2, len(keywords))
        
        source_lines = []
        for s in sessions:
            if len(source_lines) >= max_total:
                break
            session_name = s.get('name', '')
            user_lines = self._session_user_lines.get(session_name, [])
            if not user_lines and 'user_lines' in s:
                user_lines = s['user_lines']
            if not user_lines:
                continue
            
            # 过滤子进程消息
            clean_lines = []
            for idx, line_text in enumerate(user_lines):
                is_subprocess = any(re.search(pat, line_text) for pat in _SUBPROCESS_PATTERNS)
                if not is_subprocess:
                    clean_lines.append((idx, line_text))
            
            # 多关键词匹配: 统计每行命中的关键词数
            matched = []
            for idx, line_text in clean_lines:
                line_lower = line_text.lower()
                hits = sum(1 for kw in keywords if kw.lower() in line_lower)
                if hits >= min_match:
                    matched.append((idx, line_text, hits))
            
            # 按命中数降序排列，优先取最相关的行
            matched.sort(key=lambda x: -x[2])
            
            collected = 0
            if matched:
                for idx, line_text, _ in matched:
                    if collected >= max_per_session:
                        break
                    source_lines.append({
                        "text": line_text,
                        "session": session_name
                    })
                    collected += 1
            else:
                # 无精确匹配（LLM从语义判断的），fallback取首条有意义的行
                # 过滤掉长度<=4或纯寒暄的行（如"你好"、"嗯"、"好的"等）
                _GREETINGS = {'你好', '嗯', '好的', '好', '谢谢', '感谢', '是的', '对',
                              '可以', '行', '没问题', 'hi', 'hello', '嗨', '在吗'}
                for _, line_text in clean_lines:
                    stripped_text = line_text.strip()
                    if len(stripped_text) > 4 and stripped_text not in _GREETINGS:
                        source_lines.append({
                            "text": line_text,
                            "session": session_name
                        })
                        break
        
        return source_lines[:max_total]
    
    def detect(self, llm_client=None):
        """
        执行完整pipeline: 解析→标注→矩阵→判定
        
        Returns: [{
            "task": str,
            "weeks_active": [int],
            "total_count": int,
            "span": int,
            "weekly_counts": {week: count},
            "source_lines": [{"text": str, "session": str}]  # 溯源用
        }]
        """
        # Phase 1: 解析sessions
        self._parse_sessions()
        
        # Phase 2-3: LLM标注
        self._tag_all_sessions()
        
        # Phase 4: 构建矩阵
        self._build_matrix()
        
        # Phase 5: 判定
        current_week = self.total_weeks
        habits = []
        
        for task, weeks in self.task_weeks.items():
            if task in ("不明确",):
                continue
            
            weeks_sorted = sorted(weeks)
            num_weeks = len(weeks_sorted)
            span = weeks_sorted[-1] - weeks_sorted[0] + 1
            last_week = weeks_sorted[-1]
            gap = current_week - last_week
            total_count = sum(self.week_task_matrix[task].values())
            
            # 判定: 出现>=MIN_WEEKS周 + 跨度>=MIN_SPAN + 最近RECENT_WINDOW周内有出现
            is_habit = (num_weeks >= self.MIN_WEEKS and 
                       span >= self.MIN_SPAN and 
                       gap < self.RECENT_WINDOW)
            
            if is_habit:
                # 收集溯源信息: 找到包含此task的所有sessions
                related_sessions = [s for s in self.sessions 
                                   if task in s.get('tasks', []) or 
                                   self._reverse_map.get(task, '') in [self._reverse_map.get(t, t) for t in s.get('tasks', [])]]
                # 更精确: 找归一化后匹配的sessions
                matched_sessions = []
                for s in self.sessions:
                    for t in s.get('tasks', []):
                        unified = self._reverse_map.get(t, t)
                        if unified == task:
                            matched_sessions.append(s)
                            break
                
                source_lines = self._collect_source_lines(task, matched_sessions)
                
                habits.append({
                    "task": task,
                    "weeks_active": weeks_sorted,
                    "total_count": total_count,
                    "span": span,
                    "weekly_counts": dict(self.week_task_matrix[task]),
                    "source_lines": source_lines
                })
        
        # 排序
        habits.sort(key=lambda x: -x['total_count'])
        
        if self.verbose:
            print(f"\n[HabitTracker] 检出 {len(habits)} 个持续活跃事项:")
            for item in habits:
                weeks_str = ",".join(f"W{w}" for w in item['weeks_active'])
                print(f"  \u2605 {item['task']}: {item['total_count']}次 ({weeks_str}), "
                      f"溯源行数: {len(item['source_lines'])}")
        
        return habits
    
    def run(self, llm_client=None):
        """主入口，兼容旧接口"""
        return self.detect(llm_client)


# ============================================================
# CLI入口
# ============================================================
if __name__ == "__main__":
    # 确保用户历史文件存在
    filter_user_histories()
    
    tracker = HabitTracker()
    results = tracker.detect()
    
    # 保存结果
    output_path = os.path.join(os.path.dirname(__file__), "habit_results.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=list)
    print(f"\n结果已保存: {output_path}")
