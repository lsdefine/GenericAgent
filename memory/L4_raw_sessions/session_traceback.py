"""L4 Session Traceback Tool — 从 all_histories.txt 摘要溯源到完整上下文
用法:
    from session_traceback import traceback
    result = traceback("你要不断学习不断迭代直到我主动干预喊停")
    print(result['before'])   # 前文
    print(result['match'])    # 匹配的完整turn
    print(result['after'])    # 后文
"""
import zipfile, os, re
from typing import Optional

L4_DIR = os.path.dirname(os.path.abspath(__file__))
HIST_PATH = os.path.join(L4_DIR, "all_histories.txt")

# ─── 内部工具 ───

def _load_history_lines():
    with open(HIST_PATH, 'r', encoding='utf-8') as f:
        return f.readlines()

def _find_session(lines: list, target_idx: int) -> Optional[str]:
    """从目标行往上找最近的SESSION标记"""
    for i in range(target_idx, -1, -1):
        if lines[i].startswith("SESSION: "):
            return lines[i].strip().replace("SESSION: ", "")
    return None

def _session_to_zip(session: str) -> str:
    """从session名推断zip路径 (MMDD_HHMM-MMDD_HHMM → 2026-MM.zip)"""
    month = session[:2]
    return os.path.join(L4_DIR, f"2026-{month}.zip")

def _count_occurrence_in_history(lines: list, target_idx: int, session_start_idx: int) -> int:
    """计算目标行在同session中是第几次出现（用于消歧短文本）"""
    target_text = lines[target_idx].strip()
    count = 0
    for i in range(session_start_idx, target_idx + 1):
        if lines[i].strip() == target_text:
            count += 1
    return count

def _find_session_start(lines: list, target_idx: int) -> int:
    """找到当前session的起始行"""
    for i in range(target_idx, -1, -1):
        if lines[i].startswith("SESSION: "):
            return i
    return 0

def _extract_turn_boundaries(content: str):
    """解析session文件，返回每个turn的(start, user_start, response_start, end)"""
    prompt_pattern = re.compile(r'^=== Prompt === .+$', re.MULTILINE)
    user_pattern = re.compile(r'^=== USER ===$', re.MULTILINE)
    response_pattern = re.compile(r'^=== Response === .+$', re.MULTILINE)
    
    prompts = [m.start() for m in prompt_pattern.finditer(content)]
    turns = []
    for i, p_start in enumerate(prompts):
        turn_end = prompts[i+1] if i+1 < len(prompts) else len(content)
        # 找这个turn内的USER和Response标记
        segment = content[p_start:turn_end]
        u_match = user_pattern.search(segment)
        r_match = response_pattern.search(segment)
        user_pos = p_start + u_match.start() if u_match else None
        resp_pos = p_start + r_match.start() if r_match else None
        turns.append({
            'start': p_start,
            'end': turn_end,
            'user_pos': user_pos,
            'resp_pos': resp_pos,
        })
    return turns

def _get_user_text(content: str, turn: dict) -> str:
    """提取一个turn中的用户文本"""
    if turn['user_pos'] is None:
        return ""
    # USER文本在 "=== USER ===\n" 之后，到 "=== Response ===" 之前
    start = content.index('\n', turn['user_pos']) + 1
    end = turn['resp_pos'] if turn['resp_pos'] else turn['end']
    return content[start:end].strip()

def _get_response_text(content: str, turn: dict) -> str:
    """提取一个turn中的response文本"""
    if turn['resp_pos'] is None:
        return ""
    start = content.index('\n', turn['resp_pos']) + 1
    return content[start:turn['end']].strip()


# ─── 主函数 ───

def traceback(query: str, context_chars: int = 1500, nth: int = 0) -> dict:
    """从 all_histories.txt 中的文本溯源到完整上下文
    
    Args:
        query: 要搜索的文本（可以是 [USER]: xxx 或 [Agent] xxx 格式，也可以是纯文本）
        context_chars: 前后文各取多少字符（默认1500）
        nth: 如果有多个匹配，取第几个（0-based，默认第一个）
    
    Returns:
        dict with keys:
            - session: session名
            - zip_file: zip文件名
            - before: 前文（前一个turn的response尾部 + 当前turn的prompt头）
            - match: 匹配到的完整内容（用户消息或agent回复片段）
            - after: 后文（当前turn的response或下一个turn的开头）
            - turn_index: 在session中第几个turn
            - total_turns: session总turn数
            - history_context: all_histories.txt中的上下文行
    """
    lines = _load_history_lines()
    
    # 标准化查询：去掉前缀
    search_text = query.strip()
    if search_text.startswith("[USER]: "):
        search_text = search_text[8:]
        search_type = "USER"
    elif search_text.startswith("[Agent] "):
        search_text = search_text[8:]
        search_type = "AGENT"
    else:
        search_type = "AUTO"
    
    # Step 1: 在 all_histories.txt 中定位
    matches = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if search_text in stripped:
            session = _find_session(lines, i)
            if session:
                matches.append((i, session, stripped))
    
    if not matches:
        return {"error": f"未在 all_histories.txt 中找到: '{search_text[:50]}...'"}
    
    if nth >= len(matches):
        return {"error": f"只找到 {len(matches)} 个匹配，但请求第 {nth+1} 个"}
    
    target_idx, session, hist_line = matches[nth]
    
    # 获取 history 上下文（前后各3行）
    hist_ctx_start = max(0, target_idx - 3)
    hist_ctx_end = min(len(lines), target_idx + 4)
    history_context = []
    for j in range(hist_ctx_start, hist_ctx_end):
        marker = ">>>" if j == target_idx else "   "
        history_context.append(f"{marker} {lines[j].rstrip()}")
    
    # Step 2: 定位zip和文件
    zip_path = _session_to_zip(session)
    target_file = f"{session}.txt"
    
    if not os.path.exists(zip_path):
        return {"error": f"ZIP文件不存在: {zip_path}"}
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        if target_file not in zf.namelist():
            return {"error": f"Session文件 {target_file} 不在 {os.path.basename(zip_path)} 中"}
        with zf.open(target_file) as f:
            content = f.read().decode('utf-8', errors='replace')
    
    # Step 3: 在session文件中定位
    # 计算这是session内第几次出现（消歧短文本）
    session_start = _find_session_start(lines, target_idx)
    occurrence = _count_occurrence_in_history(lines, target_idx, session_start)
    
    # 搜索策略：先精确搜索，再降级
    if search_type == "USER":
        # 用户原话精确存在于 "=== USER ===" 之后
        search_key = search_text[:80] if len(search_text) > 80 else search_text
    elif search_type == "AGENT":
        # Agent摘要在 <summary> 标签内
        search_key = search_text[:60] if len(search_text) > 60 else search_text
    else:
        search_key = search_text[:60] if len(search_text) > 60 else search_text
    
    # 找到第 occurrence 次出现
    pos = -1
    start_search = 0
    for _ in range(occurrence):
        pos = content.find(search_key, start_search)
        if pos == -1:
            break
        start_search = pos + 1
    
    if pos == -1:
        # 降级：用更短的关键词
        for length in [40, 20, 10]:
            short_key = search_text[:length]
            pos = content.find(short_key)
            if pos >= 0:
                break
    
    if pos == -1:
        return {
            "error": f"在session文件中未找到匹配文本",
            "session": session,
            "zip_file": os.path.basename(zip_path),
            "history_context": "\n".join(history_context),
            "total_matches_in_history": len(matches),
        }
    
    # Step 4: 提取上下文
    before_start = max(0, pos - context_chars)
    after_end = min(len(content), pos + len(search_key) + context_chars)
    
    before_text = content[before_start:pos]
    match_text = content[pos:pos + len(search_key)]
    after_text = content[pos + len(search_key):after_end]
    
    # 边界处理：判断前文/后文是否有实质内容
    # 前文：如果只剩 "=== Prompt === ...\n=== USER ===\n" 这类header，视为无效
    before_stripped = re.sub(r'=== (Prompt|USER|Response) ===[^\n]*\n?', '', before_text).strip()
    if len(before_stripped) < 20:
        before_text = None
    
    # 后文：如果剩余内容不足20字符有效文本，视为无效
    after_stripped = re.sub(r'=== (Prompt|USER|Response) ===[^\n]*\n?', '', after_text).strip()
    if len(after_stripped) < 20:
        after_text = None
    
    # 解析turn结构获取额外信息
    turns = _extract_turn_boundaries(content)
    turn_index = -1
    for ti, turn in enumerate(turns):
        if turn['start'] <= pos < turn['end']:
            turn_index = ti
            break
    
    return {
        "session": session,
        "zip_file": os.path.basename(zip_path),
        "turn_index": turn_index,
        "total_turns": len(turns),
        "position": pos,
        "file_size": len(content),
        "before": before_text,
        "match": match_text,
        "after": after_text,
        "history_context": "\n".join(history_context),
        "total_matches_in_history": len(matches),
        "selected_match": nth,
    }


def traceback_pretty(query: str, context_chars: int = 1500, nth: int = 0) -> str:
    """格式化输出的溯源结果"""
    r = traceback(query, context_chars, nth)
    if "error" in r:
        return f"❌ {r['error']}\n" + r.get('history_context', '')
    
    output = []
    output.append(f"{'='*60}")
    output.append(f"📍 Session: {r['session']} (Turn {r['turn_index']+1}/{r['total_turns']})")
    output.append(f"📦 ZIP: {r['zip_file']} | 位置: {r['position']}/{r['file_size']}")
    output.append(f"🔍 History匹配: 第{r['selected_match']+1}/{r['total_matches_in_history']}个")
    output.append(f"{'='*60}")
    output.append(f"\n--- all_histories.txt 上下文 ---")
    output.append(r['history_context'])
    
    if r['before'] is not None:
        output.append(f"\n--- 前文 (最后{len(r['before'])}字符) ---")
        output.append(r['before'][-800:])
    else:
        output.append(f"\n--- 前文: 无（这是session的开头） ---")
    
    output.append(f"\n{'>'*20} 匹配内容 {'<'*20}")
    output.append(r['match'])
    output.append(f"{'>'*20} 匹配结束 {'<'*20}")
    
    if r['after'] is not None:
        output.append(f"\n--- 后文 (前{len(r['after'])}字符) ---")
        output.append(r['after'][:800])
    else:
        output.append(f"\n--- 后文: 无（这是session的结尾） ---")
    
    return "\n".join(output)


if __name__ == "__main__":
    # 测试
    print(traceback_pretty("你要不断学习不断迭代直到我主动干预喊停"))
