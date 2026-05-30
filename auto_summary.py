#!/usr/bin/env python3
"""
Auto-Summary: 会话日志自动摘要工具

在 Agent 工作流中自动检测关键决策点，将摘要写入 discussion_log.md。

两种模式:
  1. online(data_dict) — 作为钩子被 agent_loop 调用，传入当前轮次的上下文
  2. offline(log_path) — 对已有的 model_responses_*.txt 批量扫描

触发条件（任一条命中即触发）:
  - 用户给出明确方案选择（"选X"、"方案X"、"用X"）
  - 用户确认决策（"执行"、"确认"、"同意"、"可以"）
  - 完成一个阶段（"完成"、"结束"、"下一"）
  - 出现重要事实/结论/教训
  - 出现总结性内容（"总结"、"综上"、"所以"）

零依赖（仅标准库）。
"""

import re
import json
import os
import glob
from datetime import datetime

# ── 路径配置 ──
_script_dir = os.path.dirname(os.path.abspath(__file__))
# 当 auto_summary.py 在代码根目录时，日志在 temp/model_responses/
DEFAULT_LOG_DIR = _script_dir                  # 代码根 = GenericAgent3/
DISCUSSION_LOG = os.path.join(DEFAULT_LOG_DIR, 'discussion_log.md')


# ── 触发关键词 ──

_DECISION_PATTERNS = [
    r'(选|选择|采用|用|取)(\s*方案\s*)?[ABCD一二三四]',
    r'方案\s*[ABCD一二三四]',
    r'(选|选择)\s*方案\s*\d',
    r'(就|就按)\s*(方案|这个|这个方案|你说的)',
    r'走\s*(方案|路线|方向)\s*[ABCD一二三四]',
]

_CONFIRM_PATTERNS = [
    r'^(好|行|可以|同意|确认|执行|开始|就这么办|没问题|OK|ok)',
    r'^(确认|同意|批准)\s*(执行|开始)',
    r'(可以|同意)\s*(执行|开始|实施)',
    r'就这么\s*(定|办|决定)',
]

_COMPLETION_PATTERNS = [
    r'(完成|结束|收工|搞定|完毕|通过|交付)',
    r'下一(步|个|阶段|章节|部分)',
    r'阶段\s*\d\s*(完成|结束)',
    r'总结|综上|总而言之|总的来说',
]

_FACT_PATTERNS = [
    r'(重要|关键|核心)\s*(发现|结论|事实|教训|启示)',
    r'(记一下|记住|注意|别忘了|重要的)',
    r'(教训|经验|学到)',
    r'(原理|本质|原因)是',
    r'这是因为|原因在于|根源是',
]

# 应过滤掉的低价值状态更新模式
_FILTER_PATTERNS = [
    r'Subagent.*?(工作|Turn|到).*?完成',
    r'正在.*?执行.*?步骤',
    r'子任务.*?完成',
    r'Tool.*?returned',
    r'观察.*?结果',       # 状态观察
    r'再等一会儿|等待.*?完成|继续观察',
    r'已读取完毕',
    r'etc\.\.\.',         # 当 summary 里全是 `...`
    r'^\s*$',             # 空行
]


def _compile(*patterns):
    return [re.compile(p) for p in patterns]


# ── 辅助函数 ──

def _extract_user_text(prompt_block: str) -> str:
    """从 Prompt JSON 块中提取用户的纯文本消息（过滤掉 tool_result）。"""
    try:
        data = json.loads(prompt_block)
        if not isinstance(data, dict):
            return ''
        content = data.get('content', [])
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                text = item.get('text', '')
                if text and not text.startswith('\n### [WORKING MEMORY]') and not text.startswith('\n[SYSTEM'):
                    texts.append(text)
        return '\n'.join(texts)
    except (json.JSONDecodeError, Exception):
        return ''


def _extract_agent_text(response_block: str) -> str:
    """从 Response Python repr 中提取 Agent 的 text 内容。"""
    try:
        data = json.loads(response_block)
    except (json.JSONDecodeError, Exception):
        try:
            data = eval(response_block, {'__builtins__': {}}, {})
        except Exception:
            return ''
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return ''
    texts = []
    for item in data:
        if isinstance(item, dict) and item.get('type') == 'text':
            t = item.get('text', '')
            if t:
                texts.append(t)
    return '\n'.join(texts)


def _extract_agent_thinking(response_block: str) -> str:
    """从 Response 中提取 thinking 内容（用于话题识别）。"""
    try:
        data = json.loads(response_block)
    except Exception:
        try:
            data = eval(response_block, {'__builtins__': {}}, {})
        except Exception:
            return ''
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return ''
    thoughts = []
    for item in data:
        if isinstance(item, dict) and item.get('type') == 'thinking':
            t = item.get('thinking', '')
            if t:
                thoughts.append(t)
    return '\n'.join(thoughts)


def _extract_text_from_response(response) -> str:
    """从 LLM response 对象中提取纯文本（用于 hook 模式）。
    
    兼容:
      - Anthropic: response.content = [TextBlock(text='...'), ...]
      - OpenAI: response.content = '...'
    """
    if isinstance(response, str):
        return response
    if hasattr(response, 'content'):
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    texts.append(block.get('text', ''))
                elif hasattr(block, 'type') and block.type == 'text':
                    texts.append(getattr(block, 'text', ''))
            return '\n'.join(texts)
    # 兼容 dict 格式的 response（如 {'content': '...'}）
    if isinstance(response, dict):
        return response.get('content', str(response))
    return str(response)


def _is_low_value(text: str) -> bool:
    """判断是否为低价值的自动状态更新。"""
    if not text or len(text) < 10:
        return True
    for pat in _FILTER_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def _detect_triggers(text: str) -> list:
    """检测文本命中哪些触发条件，返回标签列表。"""
    tags = []
    if any(p.search(text) for p in _compile(*_DECISION_PATTERNS)):
        tags.append('决策:方案选择')
    if any(p.search(text) for p in _compile(*_CONFIRM_PATTERNS)):
        tags.append('决策:确认')
    if any(p.search(text) for p in _compile(*_COMPLETION_PATTERNS)):
        tags.append('阶段完成')
    if any(p.search(text) for p in _compile(*_FACT_PATTERNS)):
        tags.append('重要事实')
    return tags


def _extract_topic(user_text: str, agent_text: str, thinking: str = '') -> str:
    """从对话中提取话题名称（首句或关键句）。"""
    for text in [user_text, agent_text, thinking]:
        if not text:
            continue
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            line = re.sub(r'<summary>|</summary>', '', line).strip()
            if not line:
                continue
            if len(line) >= 8:
                return line[:80]
    return '(未能提取话题)'


def _extract_need(user_text: str) -> str:
    """从用户消息中提取需求描述（前两句话）。"""
    lines = [l.strip() for l in user_text.split('\n') if l.strip()]
    need_lines = []
    for line in lines:
        if line.startswith('{') or line.startswith('['):
            continue
        if line.startswith('<summary>') or line.startswith('###'):
            continue
        need_lines.append(line)
        if len(need_lines) >= 2:
            break
    return ' '.join(need_lines)[:120] if need_lines else '(未能提取需求)'


def _extract_decision(user_text: str, agent_text: str) -> str:
    """尝试从对话中提取明确的决策内容。"""
    combined = f"{user_text}\n{agent_text}"
    # 先清理 HTML/标签噪音
    cleaned = re.sub(r'<summary>|</summary>', '', combined)
    
    for pattern in _DECISION_PATTERNS + _CONFIRM_PATTERNS:
        m = re.search(pattern, cleaned, re.MULTILINE)
        if m:
            start = max(0, m.start() - 40)
            end = min(len(cleaned), m.end() + 40)
            context = cleaned[start:end].replace('\n', ' ')
            context = context.strip()
            # 过滤掉含有文件路径的片段
            if re.search(r'[/\\][\w.-]+\.[\w]+', context):
                continue
            return context[:100]
    
    for sentence in re.split(r'[。！？\n]', cleaned):
        # 要求句子不包含文件路径
        if re.search(r'[/\\][\w.-]+\.[\w]+', sentence):
            continue
        # 关键词检查（不含"用"，因其太常见如"用户""使用"）
        if any(kw in sentence for kw in ['选', '决定', '确认', '同意']):
            if len(sentence) > 5:
                return sentence.strip()[:100]
    
    return ''


def _generate_tags(user_text: str, agent_text: str, trigger_tags: list) -> list:
    """自动生成标签。"""
    tags = set(trigger_tags)
    combined = (user_text + ' ' + agent_text).lower()
    keyword_tags = {
        '写作': '#写作', '代码': '#代码', 'bug': '#bug',
        '部署': '#部署', '调试': '#调试', '测试': '#测试',
        '设计': '#设计', '方案': '#方案', 'pr': '#PR',
        'github': '#GitHub', '文档': '#文档', '配置': '#配置',
        '浏览器': '#浏览器', '搜索': '#搜索', '蛋白质': '#蛋白质',
        '模型': '#模型', '数据': '#数据', '复盘': '#复盘',
        '计划': '#计划', '决策': '#决策', '讨论': '#讨论',
        '交付': '#交付', '邮件': '#邮件',
    }
    for kw, tag in keyword_tags.items():
        if kw in combined:
            tags.add(tag)
    return sorted(tags)


def _format_entry(timestamp: str, topic: str, need: str,
                  discussion: str, decision: str, tags: list) -> str:
    """格式化为 Markdown 条目。"""
    parts = ['---', f'{timestamp}']
    if topic:
        parts.append(f'  话题: {topic}')
    if need:
        parts.append(f'  用户需求: {need}')
    if discussion:
        if len(discussion) > 200:
            discussion = discussion[:200] + '...'
        parts.append(f'  讨论内容: {discussion}')
    if decision:
        parts.append(f'  决策: {decision}')
    if tags:
        parts.append(f'  标签: {" ".join(tags)}')
    parts.append('')
    return '\n'.join(parts)


def _last_entry_hash(log_path: str) -> str:
    """读取最后一个条目的粗略 hash（去重用）。"""
    if not os.path.isfile(log_path):
        return ''
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        entries = content.strip().split('\n---\n')
        if entries and entries[-1].strip():
            # 取最后条目的前 80 个字符作为 hash
            return entries[-1].strip()[:80]
        return ''
    except Exception:
        return ''


# ═══════════════════════════════════════════════
#  管道模式（Online）：单轮次摘要
# ═══════════════════════════════════════════════

def online(user_message: str = '', agent_response: str = '',
           turn: int = 0, timestamp: str = '',
           log_path: str = None,
           response_obj=None) -> dict:
    """
    在线模式：传入当前轮次的用户消息和 Agent 回复，检测是否需写摘要。

    参数:
      user_message: 当前轮次的用户消息（纯文本）
      agent_response: 当前轮次的 Agent 回复（纯文本）
      turn: 轮次数
      timestamp: 时间戳字符串（如 '2026-05-30 11:45'）
      log_path: discussion_log.md 路径
      response_obj: 原始 LLM response 对象（用于自动提取 agent_response）

    返回:
      {'written': bool, 'tags': list, 'entry': str}
    """
    if log_path is None:
        log_path = DISCUSSION_LOG
    
    if not timestamp:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # 如果传入了 response_obj，自动提取 agent_response
    if response_obj and not agent_response:
        agent_response = _extract_text_from_response(response_obj) or ''
    
    # 如果 user_message 和 agent_response 都为空，跳过
    if not user_message and not agent_response:
        return {'written': False, 'tags': [], 'entry': ''}
    
    # 检测是否为低价值状态更新
    combined = f"{user_message}\n{agent_response}"
    if _is_low_value(combined):
        return {'written': False, 'tags': [], 'entry': ''}
    
    # 检测触发
    trigger_tags = _detect_triggers(combined)
    
    if not trigger_tags:
        return {'written': False, 'tags': [], 'entry': ''}
    
    # 提取信息
    topic = _extract_topic(user_message, agent_response)
    need = _extract_need(user_message) if user_message else ''
    discussion = agent_response[:200] if agent_response else ''
    decision = _extract_decision(user_message, agent_response)
    tags = _generate_tags(user_message, agent_response, trigger_tags)
    
    # 格式化为 Markdown 条目
    entry = _format_entry(timestamp, topic, need, discussion, decision, tags)
    
    # 去重检查：与最后一条比较
    last_hash = _last_entry_hash(log_path)
    if last_hash and entry.strip()[:80] == last_hash:
        return {'written': False, 'tags': tags, 'entry': entry.strip(), 'dedup': True}
    
    # 写入日志
    log_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(entry + '\n')
    
    return {'written': True, 'tags': tags, 'entry': entry.strip()}


# ═══════════════════════════════════════════════
#  离线模式：扫描已有日志文件
# ═══════════════════════════════════════════════

def _parse_log_file(filepath: str) -> list:
    """
    解析 model_responses_*.txt，返回轮次列表。
    每轮: {'timestamp': str, 'user_msg': str, 'agent_msg': str, 'thinking': str}
    """
    turns = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    blocks = re.split(r'^=== (Prompt|Response) === (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\n',
                      content, flags=re.MULTILINE)
    
    current_prompt_ts = None
    current_prompt_body = None
    
    i = 0
    while i < len(blocks):
        if blocks[i] in ('Prompt', 'Response'):
            label = blocks[i]
            ts = blocks[i+1]
            body = blocks[i+2] if i+2 < len(blocks) else ''
            i += 3
            
            if label == 'Prompt':
                current_prompt_ts = ts
                current_prompt_body = body
            elif label == 'Response':
                if current_prompt_ts:
                    user_text = _extract_user_text(current_prompt_body or '')
                    agent_text = _extract_agent_text(body)
                    thinking = _extract_agent_thinking(body)
                    turns.append({
                        'timestamp': current_prompt_ts,
                        'user_msg': user_text,
                        'agent_msg': agent_text,
                        'thinking': thinking,
                    })
                    current_prompt_ts = None
                    current_prompt_body = None
        else:
            i += 1
    
    return turns


def offline(log_path: str = None, output_path: str = None,
            all_files: bool = True, max_files: int = 0) -> dict:
    """
    离线模式：扫描已有日志文件，批量生成摘要。

    参数:
      log_path: 单个日志文件路径（如果指定，则只扫这个文件）
      output_path: discussion_log.md 路径（默认为 temp/discussion_log.md）
      all_files: 是否扫描 model_responses/ 下所有文件
      max_files: 扫描文件数上限（0=不限，仅当 all_files=True 时生效）

    返回:
      {'entries_written': int, 'files_scanned': int, 'turns_analyzed': int}
    """
    if output_path is None:
        output_path = DISCUSSION_LOG
    
    if log_path:
        files = [log_path]
    else:
        responses_dir = os.path.join(DEFAULT_LOG_DIR, 'temp', 'model_responses')
        if not os.path.isdir(responses_dir):
            # 回退：从 temp/ 外的代码根找
            responses_dir = os.path.join(DEFAULT_LOG_DIR, 'model_responses')
        files = sorted(glob.glob(os.path.join(responses_dir, 'model_responses_*.txt')))
        if max_files > 0 and len(files) > max_files:
            files = files[-max_files:]
    
    total_entries = 0
    total_turns = 0
    
    for fpath in files:
        if not os.path.isfile(fpath):
            continue
        try:
            turns = _parse_log_file(fpath)
        except Exception as e:
            print(f"  ⚠ 解析失败: {fpath} — {e}")
            continue
        
        total_turns += len(turns)
        
        for turn_data in turns:
            result = online(
                user_message=turn_data['user_msg'],
                agent_response=turn_data['agent_msg'],
                timestamp=turn_data['timestamp'][:16],
                log_path=output_path,
            )
            if result.get('written'):
                total_entries += 1
    
    return {
        'entries_written': total_entries,
        'files_scanned': len(files),
        'turns_analyzed': total_turns,
    }


# ═══════════════════════════════════════════════
#  命令行入口
# ═══════════════════════════════════════════════

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Auto-Summary: 会话日志自动摘要工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 扫描所有日志生成摘要
  python auto_summary.py

  # 扫描单个日志文件
  python auto_summary.py -f model_responses_967045.txt

  # 指定输出路径
  python auto_summary.py -o ~/discussion_log.md
        """
    )
    parser.add_argument('-f', '--file', help='指定单个日志文件路径')
    parser.add_argument('-o', '--output', help='discussion_log.md 输出路径')
    parser.add_argument('-n', '--max-files', type=int, default=0,
                        help='扫描文件数上限（0=全部）')
    
    args = parser.parse_args()
    
    print("Auto-Summary 开始扫描...")
    print(f"  输出目标: {args.output or DISCUSSION_LOG}")
    
    result = offline(
        log_path=args.file,
        output_path=args.output,
        all_files=(args.max_files == 0),
        max_files=args.max_files,
    )
    
    print(f"  扫描文件: {result['files_scanned']}")
    print(f"  分析轮次: {result['turns_analyzed']}")
    print(f"  写入条目: {result['entries_written']}")
    print("完成。")


if __name__ == '__main__':
    main()
