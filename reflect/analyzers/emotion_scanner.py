"""情绪扫描器 (原轴1/EmotionDetector 的语义化重构)

核心改动：
- 语义化命名: EmotionScanner
- 输出增加 traceback_query + occurrence_nth 字段，可直接调 session_traceback 溯源
- 基于 all_user_histories.txt（仅用户行）工作
- 保留完整LLM批处理+滑动窗口聚类逻辑
"""
import sys, json, re, time, os
from collections import Counter

# 统一配置
try:
    from reflect.analyzers._config import PROJECT_ROOT, HIST_PATH, USER_HIST_PATH, get_llm_config, filter_user_histories
    from reflect.analyzers._json_utils import robust_json_parse
except (ImportError, ModuleNotFoundError):
    from _config import PROJECT_ROOT, HIST_PATH, USER_HIST_PATH, get_llm_config, filter_user_histories
    from _json_utils import robust_json_parse

from llmcore import LLMSession

# ============================================================
# 系统提示词 (经过真实数据验证, 0假阳性)
# ============================================================
SYSTEM_PROMPT = """你是一个精确的情绪波动检测器。你的任务是找出用户在与AI助手交互中"失去冷静"的瞬间——即出现了超出正常沟通所需的情绪化表达。

## 核心原则
正常的纠正、指出错误、提出要求都是冷静的沟通行为，不算情绪波动。
只有当用户的表达方式本身变得情绪化、不必要地激烈、或明显超出理性沟通所需时，才标记。

## NEGATIVE（用户情绪超出冷静沟通范围）
满足以下任一条件：
1. 【强】表达方式明显情绪化，出现不必要的激烈语言（confidence 4-5）
2. 【中】语气中带有明显的不耐烦、挫败或嘲讽，虽未爆发但已偏离理性沟通（confidence 2-3）

强信号（conf 4-5）：
- 累积挫败后的爆发（"我都说了多少遍了"、"你到底有没有在听"、"我真的服了"）
- 讽刺/反问攻击（"你是不是根本不会"、"这也叫完成了？"）
- 夸张化表达（"每次都是这样"、"从来没有一次对的"、"完全是在浪费时间"）
- 情绪词/语气词堆叠（"真的很无语"、"太离谱了"）
- 威胁/最后通牒语气（"再这样我就不用了"）
- 人身化批评（"你太笨了"、"你是不是傻"）

中信号（conf 2-3）：
- 反复纠正同一问题后语气变得生硬/急促（"不是！是X！"、"我说的是Y不是Z！"）
- 用反问句表达对AI能力的质疑（"你有认真看吗"、"这不是很明显吗"）
- 命令语气突然加重，带有"你给我..."、"你必须..."等强制性表达
- 用"又"、"还是"、"依然"等词暗示AI反复犯同样错误时带有不满语气
- 明确表达失望但未爆发（"我本来以为你能..."、"算了我自己来"带叹气感）

弱信号（conf 1-2）：
- 冷淡地放弃/跳过（"算了不弄了"、"跳过这个吧"语气中隐含对AI无能的失望）
- 突然变得简短冷淡（之前详细交流，突然只回"行"、"随便"、"你看着办"暗示不想再解释）
- 带有轻微讽刺的确认（"好吧好吧"、"行吧你说的对"明显敷衍）
- 不得不降低期望（"那就先这样吧"、"凑合用吧"暗示不满意但放弃争取）
- 第二次以上纠正同一类错误，虽然语气平静但能感受到耐心在消耗

## POSITIVE（用户情绪化地表达惊喜/兴奋）
同样要求表达超出正常确认：
- 惊喜爆发（"卧槽这也行"、"太牛了吧"、"我靠完美"）
- 兴奋到语无伦次或用大量感叹号
- 超预期的强烈赞美（不是简单的"不错"而是"这简直是神作"）

## NEUTRAL（默认——绝大多数发言应该是这个）
以下全部是NEUTRAL，无论内容多么"负面"：
- 冷静地指出错误（"这里不对，应该是X"）→ 正常沟通
- 冷静地纠正理解（"我指的不是这个"）→ 正常沟通
- 冷静地表达不满意（"这个方案不太行，换一个"）→ 正常沟通
- 要求重做（"重新来"、"不是这样的"）→ 正常沟通
- 简单确认/赞同（"好的"、"可以"、"不错"、"做得好"）→ 正常沟通
- 描述问题/bug → 正常沟通
- 布置任务/给信息 → 正常沟通
- 对自己的代码/产品不满 → 与AI无关

## 判断技巧
问自己：如果把这句话的"情绪化修饰"去掉，信息量会减少吗？
- 如果去掉情绪化部分后信息完整 → 说明情绪化是多余的 → 标记
- 如果表达本身就是在传递信息 → 正常沟通 → NEUTRAL

## 输出格式
仅输出JSON数组，每条非NEUTRAL的结果：
[{"id": N, "label": "NEGATIVE"|"POSITIVE", "confidence": 1-5, "reason": "一句话理由"}]
如果全部NEUTRAL，输出空数组: []"""


class EmotionScanner:
    """LLM情绪检测器 + 波动聚类分析 + 溯源信息"""
    
    BATCH_SIZE = 20          # 每批送LLM的条数
    WINDOW_SIZE = 50         # 滑动窗口大小(行)
    TIER1_THRESHOLD = 12     # 波动分阈值(密度x平均conf)
    TIER2_MIN_CONF = 5       # 孤立高强度点的最低confidence
    
    def __init__(self, hist_path=None, verbose=True):
        """
        Args:
            hist_path: 用户历史文件路径(应为过滤后的all_user_histories.txt)
                       如果为None，自动使用USER_HIST_PATH
            verbose: 是否打印进度
        """
        self.hist_path = hist_path or USER_HIST_PATH
        self.verbose = verbose
        # 用于计算occurrence_nth的计数器
        self._text_occurrence_counter = Counter()
        
    def _load_user_lines(self, start_line=None, end_line=None):
        """加载指定区间的USER行，返回[(line_no, text), ...]"""
        with open(self.hist_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        start = (start_line or 1) - 1
        end = end_line or len(lines)
        
        user_lines = []
        for i, line in enumerate(lines[start:end], start=start+1):
            stripped = line.strip()
            if stripped.startswith("[USER]:"):
                user_lines.append((i, stripped[:300]))  # 截断过长文本
        return user_lines
    
    def _build_traceback_info(self, text, line_no):
        """构建溯源信息，可直接传给session_traceback.traceback()
        
        Args:
            text: 原始用户行文本（含[USER]:前缀）
            line_no: 在hist文件中的行号
            
        Returns:
            dict with traceback_query (去掉[USER]:前缀的纯文本) 和 occurrence_nth
        """
        # 去掉[USER]:前缀得到纯文本query
        query = text
        if query.startswith("[USER]:"):
            query = query[7:].strip()
        
        # 计算这段文本是第几次出现(nth)
        nth = self._text_occurrence_counter[query]
        self._text_occurrence_counter[query] += 1
        
        return {
            "traceback_query": query,
            "occurrence_nth": nth
        }
    
    def _call_llm(self, batch_text, llm_client=None):
        """调用LLM进行情绪分析，返回解析后的列表"""
        if llm_client:
            session = llm_client
        else:
            session = LLMSession(get_llm_config())
        session.system = SYSTEM_PROMPT
        
        gen = session.ask(f"分析以下用户发言：\n\n{batch_text}")
        result = ''.join(gen)
        
        # 鲁棒JSON解析
        items = robust_json_parse(result, expect_type="array")
        if items is None:
            if self.verbose:
                print(f"  [WARN] JSON解析失败: {result[:200]}")
            return []
        return items
    
    def detect(self, start_line=None, end_line=None, llm_client=None):
        """
        执行情绪检测，返回所有检出结果（含溯源信息）
        
        Returns: [{
            "line_no": int, "label": str, "confidence": int, 
            "reason": str, "text": str,
            "traceback_query": str,   # 可直接传给session_traceback
            "occurrence_nth": int     # 第几次出现，传给nth参数
        }]
        """
        user_lines = self._load_user_lines(start_line, end_line)
        if self.verbose:
            print(f"[EmotionScanner] 加载 {len(user_lines)} 条USER行 (L{start_line or 1}~L{end_line or 'END'})")
        
        # 重置计数器
        self._text_occurrence_counter = Counter()
        all_detections = []
        
        # 分批处理
        for batch_start in range(0, len(user_lines), self.BATCH_SIZE):
            batch = user_lines[batch_start:batch_start + self.BATCH_SIZE]
            batch_text = "\n".join([f"[{i+1}] {text}" for i, (ln, text) in enumerate(batch)])
            
            results = self._call_llm(batch_text, llm_client)
            
            for item in results:
                idx = item.get('id', 0) - 1
                if 0 <= idx < len(batch):
                    ln, text = batch[idx]
                    tb_info = self._build_traceback_info(text, ln)
                    all_detections.append({
                        "line_no": ln,
                        "label": item['label'],
                        "confidence": item['confidence'],
                        "reason": item['reason'],
                        "text": text,
                        "traceback_query": tb_info['traceback_query'],
                        "occurrence_nth": tb_info['occurrence_nth']
                    })
            
            if self.verbose:
                neg_count = sum(1 for r in results if r.get('label') == 'NEGATIVE')
                print(f"  批次 {batch_start//self.BATCH_SIZE + 1}/{(len(user_lines)-1)//self.BATCH_SIZE + 1}: "
                      f"{neg_count}条负面 / {len(batch)}条")
            
            time.sleep(0.3)  # 避免rate limit
        
        return all_detections
    
    def cluster(self, detections):
        """
        对检测结果进行波动聚类分析
        Returns: {"tier1_clusters": [...], "tier2_isolated": [...]}
        """
        negatives = sorted([d for d in detections if d['label'] == 'NEGATIVE'], 
                          key=lambda x: x['line_no'])
        
        if not negatives:
            return {"tier1_clusters": [], "tier2_isolated": []}
        
        # 滑动窗口聚类
        windows = []
        i = 0
        while i < len(negatives):
            window_start = negatives[i]['line_no']
            window_end = window_start + self.WINDOW_SIZE
            
            # 收集窗口内的所有负面检出
            window_items = []
            j = i
            while j < len(negatives) and negatives[j]['line_no'] <= window_end:
                window_items.append(negatives[j])
                j += 1
            
            if len(window_items) >= 2:  # 至少2条才算聚类
                avg_conf = sum(item['confidence'] for item in window_items) / len(window_items)
                score = len(window_items) * avg_conf
                windows.append({
                    "start": window_items[0]['line_no'],
                    "end": window_items[-1]['line_no'],
                    "count": len(window_items),
                    "avg_conf": round(avg_conf, 1),
                    "score": round(score, 1),
                    "items": window_items
                })
                i = j  # 跳过已处理的
            else:
                i += 1
        
        # 去重合并重叠窗口
        merged = []
        for w in sorted(windows, key=lambda x: -x['score']):
            overlap = False
            for m in merged:
                if not (w['end'] < m['start'] - 10 or w['start'] > m['end'] + 10):
                    overlap = True
                    break
            if not overlap:
                merged.append(w)
        
        # 分级
        tier1 = sorted([w for w in merged if w['score'] >= self.TIER1_THRESHOLD], 
                      key=lambda x: -x['score'])
        
        # 找孤立高强度点(conf=5且不在任何cluster中)
        clustered_lines = set()
        for w in merged:
            for item in w['items']:
                clustered_lines.add(item['line_no'])
        
        tier2 = [d for d in negatives 
                 if d['confidence'] >= self.TIER2_MIN_CONF 
                 and d['line_no'] not in clustered_lines]
        
        return {"tier1_clusters": tier1, "tier2_isolated": tier2}
    
    def run(self, start_line=None, end_line=None, llm_client=None):
        """
        完整流程: 检测 -> 聚类 -> 输出
        Returns: 完整结果字典
        """
        # Step 1: LLM检测
        detections = self.detect(start_line, end_line, llm_client)
        
        # Step 2: 聚类分析
        clusters = self.cluster(detections)
        
        # Step 3: 统计
        user_lines = self._load_user_lines(start_line, end_line)
        neg_count = sum(1 for d in detections if d['label'] == 'NEGATIVE')
        pos_count = sum(1 for d in detections if d['label'] == 'POSITIVE')
        
        result = {
            "tier1_clusters": clusters['tier1_clusters'],
            "tier2_isolated": clusters['tier2_isolated'],
            "all_detections": detections,
            "stats": {
                "total_user_lines": len(user_lines),
                "total_negative": neg_count,
                "total_positive": pos_count,
                "detection_rate": round(neg_count / max(len(user_lines), 1) * 100, 1),
                "tier1_count": len(clusters['tier1_clusters']),
                "tier2_count": len(clusters['tier2_isolated']),
                "deep_dive_positions": len(clusters['tier1_clusters']) + len(clusters['tier2_isolated'])
            }
        }
        
        if self.verbose:
            print(f"\n[EmotionScanner 结果汇总]")
            print(f"  总USER行: {result['stats']['total_user_lines']}")
            print(f"  负面检出: {neg_count} ({result['stats']['detection_rate']}%)")
            print(f"  Tier1爆发区: {result['stats']['tier1_count']}个")
            print(f"  Tier2孤立高强度: {result['stats']['tier2_count']}个")
            print(f"  需深挖位置: {result['stats']['deep_dive_positions']}个")
        
        return result


# ============================================================
# CLI入口
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="情绪扫描器")
    parser.add_argument("--start", type=int, default=None, help="起始行号")
    parser.add_argument("--end", type=int, default=None, help="结束行号")
    parser.add_argument("--output", type=str, default="emotion_results.json", help="输出文件")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    args = parser.parse_args()
    
    # 确保用户历史文件存在
    filter_user_histories()
    
    scanner = EmotionScanner(verbose=not args.quiet)
    results = scanner.run(start_line=args.start, end_line=args.end)
    
    # 保存结果
    output = {
        "stats": results['stats'],
        "tier1_clusters": [{
            "start": c['start'], "end": c['end'], 
            "count": c['count'], "score": c['score'],
            "items": [{
                "text": item['text'][:100],
                "traceback_query": item['traceback_query'][:100],
                "occurrence_nth": item['occurrence_nth'],
                "confidence": item['confidence']
            } for item in c['items'][:5]]
        } for c in results['tier1_clusters']],
        "tier2_isolated": [{
            "line_no": d['line_no'], "confidence": d['confidence'],
            "text": d['text'][:100], "reason": d['reason'],
            "traceback_query": d['traceback_query'][:100],
            "occurrence_nth": d['occurrence_nth']
        } for d in results['tier2_isolated']]
    }
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {args.output}")
