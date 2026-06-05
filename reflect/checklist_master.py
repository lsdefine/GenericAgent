import json, time, random
from pathlib import Path
from urllib import request

INTERVAL = 60
ONCE = False
_folder = None
_last_post_id = -1

def init(a):
    global _folder
    _folder = Path(a.get('mr_folder', ''))

def _load():
    p = _folder / "state.json"
    if not p.exists(): return None
    return json.loads(p.read_text("utf-8"))

def _poll_bbs(data):
    global _last_post_id
    bbs = data.get("bbs")
    if not bbs: return []
    url, key = bbs.get("url", ""), bbs.get("key", "")
    if not url: return []
    try:
        req = request.Request(f"{url}/posts?limit=20&key={key}")
        posts = json.loads(request.urlopen(req, timeout=10).read())
        if not posts: return []
        new = [p for p in posts if p['id'] > _last_post_id]
        _last_post_id = max(p['id'] for p in posts)
        return new
    except Exception:
        return []

def check():
    check.times = getattr(check, "times", 0) + 1
    if check.times > 1000: return '/exit'
    if not _folder: return '/exit'
    data = _load()
    if not data or data.get("closed"): return '/exit'
    bbs = data.get("bbs")
    if not bbs: return _prompt(data, [])
    # mapreduce: 轮询BBS
    new_posts = _poll_bbs(data)
    tasks = data.get("tasks", [])
    has_open = any(t["result"] is None for t in tasks)
    if new_posts and has_open: return _prompt(data, new_posts)
    if not has_open and (not tasks or random.random() < 0.2): return _prompt(data, new_posts)
    return None

def _prompt(data, new_posts):
    bbs = data.get("bbs")
    goal = data.get("goal", "")
    mode = "mapreduce" if bbs else "checklist"
    if new_posts:
        trigger = "有新回帖，去BBS查看并验收"
    elif any(t["result"] is None for t in data.get("tasks", [])):
        trigger = "有未完成任务，继续执行" if not bbs else "有未完成任务，派发"
    else: trigger = "无未完成任务，该plan下一步了"
    lines = [f"你是 Checklist Master（{mode}模式）。阅读 checklist_sop.md 21行之后按 Master 行事。"]
    if bbs: lines.append(f"BBS API文档（requests）: GET {bbs['url']}/readme?key={bbs['key']}")
    lines.append(f"目标: {goal}")
    lines.append(f"唤醒原因: {trigger}")
    lines.append(f'用 checklist_helper 的 CL("{_folder}") 管理状态（look/add/mark/close）。按决策树行动。')
    if bbs: lines.append("【禁止】你只负责派发+轮询+验收，绝不自己执行任务。")
    return "\n".join(lines)
