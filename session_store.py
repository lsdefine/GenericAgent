import glob
import os
import re
import uuid
from datetime import datetime


def _now():
    return datetime.now().astimezone()


class SessionStore:
    """Manage human-readable text session logs under temp/sessions."""

    def __init__(self, project_root):
        self.project_root = os.path.abspath(project_root)
        self.root_dir = os.path.join(self.project_root, "temp", "sessions")
        os.makedirs(self.root_dir, exist_ok=True)

    def start_session(self, title, source="user", model="", cwd=None):
        now = _now()
        session_id = uuid.uuid4().hex[:6]
        path = os.path.join(
            self.root_dir,
            f"{now:%Y}",
            f"{now:%m}",
            f"{now:%d}",
            f"{now:%H%M%S}-{session_id}.txt",
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return {"path": path}

    def clear_current(self):
        return None

    def append_prompt(self, session, prompt_text):
        if not session or not session.get("path"):
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(session["path"], "a", encoding="utf-8", errors="replace") as f:
            f.write(f"=== Prompt === {timestamp}\n{prompt_text}\n")

    def append_response(self, session, response_text):
        if not session or not session.get("path"):
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(session["path"], "a", encoding="utf-8", errors="replace") as f:
            f.write(f"=== Response === {timestamp}\n{response_text}\n\n")

    def restore_latest_history(self):
        files = glob.glob(os.path.join(self.root_dir, "*", "*", "*", "*.txt"))
        # 兼容旧版本的日志文件，之前保存在 temp/ 目录下，文件名以 model_responses_ 开头
        legacy_files = glob.glob(os.path.join(self.project_root, "temp", "model_responses_*.txt")) 
        all_files = files + legacy_files
        if not all_files:
            return None, "❌ 没有找到历史记录"
        latest = max(all_files, key=os.path.getmtime)
        with open(latest, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        users = re.findall(r"=== USER ===\n(.+?)(?==== |$)", content, re.DOTALL)
        resps = re.findall(r"=== Response ===.*?\n(.+?)(?==== Prompt|$)", content, re.DOTALL)
        restored = []
        for user_text, resp_text in zip(users, resps):
            user_text = user_text.strip()
            resp_text = resp_text.strip()[:500]
            if user_text and resp_text:
                restored.extend([f"[USER]: {user_text}", f"[Agent] {resp_text}"])
        if not restored:
            return None, "❌ 历史记录里没有可恢复内容"
        session = {"path": latest}
        return (restored, os.path.basename(latest), len(restored) // 2, session), None
