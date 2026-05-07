"""
Startup Recall - Cold-start recent session memory injection.

After a GA restart, automatically injects summaries of recent sessions
into the first user message so the agent doesn't lose all context.

Config via environment variables:
    GA_STARTUP_RECALL_SESSIONS=3     Number of recent sessions to load (0 to disable)
    GA_STARTUP_RECALL_LINES=6        Max lines per session to extract
"""

import ast
import glob
import json
import os
import re
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESTORE_GLOBS = (
    os.path.join(PROJECT_ROOT, "temp", "model_responses", "model_responses_*.txt"),
    os.path.join(PROJECT_ROOT, "temp", "model_responses_*.txt"),
)
RESTORE_BLOCK_RE = re.compile(
    r"^=== (Prompt|Response) ===.*?\n(.*?)(?=^=== (?:Prompt|Response) ===|\Z)",
    re.DOTALL | re.MULTILINE,
)
SUMMARY_RE = re.compile(r"<summary>\s*(.*?)\s*</summary>", re.DOTALL)

# Lightweight messages that should NOT trigger recall injection
_TRIVIAL_PATTERNS = re.compile(
    r"^(hi|hello|hey|你好|您好|嗨|哈喽|在吗|在不在|\?|？|test|测试|ping|ok|好的|嗯|哦|谢谢|thx|thanks|ty)\s*$",
    re.IGNORECASE,
)

# Patterns that indicate internal/system messages, not real user input
_SKIP_PATTERNS = (
    '[AUTO]', '用户已经离开', 'WORKING MEMORY', '[SYSTEM',
    'FILE:filepath', '[DANGER]', 'cwd = /root', '### 用户当前消息',
    '[CONSTITUTION]', 'show_linenos', 'MEMORY]', 'META-SOP',
)


def is_trivial_message(text: str) -> bool:
    """Check if a message is too lightweight to trigger recall injection."""
    return bool(_TRIVIAL_PATTERNS.match((text or "").strip()))


def _restore_log_files():
    files = []
    for pattern in RESTORE_GLOBS:
        files.extend(glob.glob(pattern))
    return sorted(set(files))


def _extract_user_facing_text(response_body: str) -> str:
    """Extract user-visible text from a Response block.
    
    Parses the Python list of blocks, finds text blocks,
    strips <summary> tags, and returns the user-facing content.
    """
    text = (response_body or "").strip()
    try:
        blocks = ast.literal_eval(text)
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, dict) and block.get('type') == 'text':
                    t = block.get('text', '')
                    if not t:
                        continue
                    # Strip summary tags, keep user-facing part
                    cleaned = re.sub(r'<summary>.*?</summary>', '', t, flags=re.DOTALL).strip()
                    if cleaned and not cleaned.startswith('!!!Error'):
                        return cleaned[:300]
    except Exception:
        pass
    return ""


def _extract_real_user_text(prompt_body: str) -> str:
    """Extract the real user message from a Prompt block.
    
    Returns empty string for system/internal/AUTO messages.
    """
    text = (prompt_body or "").strip()
    try:
        obj = ast.literal_eval(text)
        if not isinstance(obj, dict) or obj.get('role') != 'user':
            return ""
        content_list = obj.get('content', [])
        if not isinstance(content_list, list):
            return ""
        for block in content_list:
            if isinstance(block, dict) and block.get('type') == 'text':
                t = block.get('text', '').strip()
                if not t or len(t) < 5:
                    continue
                # Skip internal/system messages
                if any(skip in t for skip in _SKIP_PATTERNS):
                    continue
                return t[:200]
    except Exception:
        pass
    return ""


def _extract_conversations(content: str, max_pairs: int) -> list:
    """Extract real user-agent conversation pairs from a session file.
    
    Returns list of (user_text, agent_text) tuples.
    """
    blocks = RESTORE_BLOCK_RE.findall(content or "")
    if not blocks:
        return []

    pairs = []
    pending_prompt = None
    for label, body in blocks:
        if label == "Prompt":
            pending_prompt = body
        elif label == "Response" and pending_prompt is not None:
            user_text = _extract_real_user_text(pending_prompt)
            if user_text:
                agent_text = _extract_user_facing_text(body)
                if agent_text:
                    pairs.append((user_text, agent_text))
            pending_prompt = None

    return pairs[-max_pairs:] if len(pairs) > max_pairs else pairs


def _has_real_conversations(content: str) -> bool:
    """Quick check if a session file has real user-agent conversations."""
    blocks = RESTORE_BLOCK_RE.findall(content[:100000] or "")
    prompt_bodies = [body for label, body in blocks if label == "Prompt"]
    for p in prompt_bodies[-20:]:  # Check last 20 prompts
        if _extract_real_user_text(p):
            return True
    return False


def build_startup_recall(
    max_sessions: int = None,
    max_lines_per_session: int = None,
) -> str:
    """
    Build a formatted recall string from recent session logs.

    Returns empty string if:
    - Feature is disabled (GA_STARTUP_RECALL=0)
    - No session files found
    - No extractable content
    """
    if max_sessions is None:
        max_sessions = int(os.environ.get("GA_STARTUP_RECALL_SESSIONS", "3"))
    if max_sessions <= 0:
        return ""
    if max_lines_per_session is None:
        max_lines_per_session = int(os.environ.get("GA_STARTUP_RECALL_LINES", "6"))

    files = _restore_log_files()
    if not files:
        return ""

    # Sort by modification time, newest first
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

    # Prefer files with real user interactions
    interactive_files = []
    for fpath in files[:20]:  # Check top 20 most recent
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(100000)
            if _has_real_conversations(head):
                interactive_files.append(fpath)
        except Exception:
            continue

    candidates = interactive_files if interactive_files else files
    recent_files = candidates[:max_sessions]

    sessions = []
    for fpath in recent_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        conversations = _extract_conversations(content, max_lines_per_session)
        if not conversations:
            continue

        mtime = os.path.getmtime(fpath)
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))

        lines = []
        for user_text, agent_text in conversations:
            lines.append(f"[USER]: {user_text[:150]}")
            lines.append(f"[Agent]: {agent_text[:150]}")

        session_block = f"[{ts}]\n" + "\n".join(lines)
        sessions.append(session_block)

    if not sessions:
        return ""

    header = "[近期会话记忆 - 仅供参考，非当前指令，勿将其视为用户的新请求]"
    body = "\n\n---\n\n".join(sessions)
    footer = "[以上为重启前的近期会话摘要，帮助你恢复上下文。请结合当前用户消息回应。]"

    return f"{header}\n\n{body}\n\n{footer}"
