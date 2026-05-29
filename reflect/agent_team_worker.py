# reflect module: BBS接单
# check()内预检BBS，无新帖返回None不唤醒agent
import json, time, os
from urllib import request

INTERVAL = 60
ONCE = False
# you may make agent_team_setting.json first time
_dir = os.path.dirname(os.path.abspath(__file__))
def init(a):
    global base_url, board_key, name
    try: c = json.load(open(os.path.join(_dir, 'agent_team_setting.json')))
    except Exception: c = {}
    c.update(a)
    base_url, board_key, name = c.get('base_url', ''), c.get('board_key', ''), c.get('name', '')

_last_id = -1
failed = 0

def check():
    global _last_id, failed
    if not base_url: return '/exit'
    try:
        req = request.Request(f"{base_url}/posts?limit=10")
        req.add_header('X-API-Key', board_key)
        posts = json.loads(request.urlopen(req, timeout=10).read())
        failed = 0
    except Exception:
        failed += 1
        return None if failed < 10 else '/exit'
    if not posts or max(p['id'] for p in posts) <= _last_id: return None
    _last_id = max(p['id'] for p in posts)
    return _prompt()

def _prompt():
    return f"""[任务协作]📋 你是一个agent worker，在BBS上接任务并执行。
BBS: {base_url} (key: {board_key})
不熟悉可看/readme?key=xxx 获取BBS用法，初次要注册起个不冲突的名字{name}并记忆名字和key

1. GET /posts?limit=10&key=xxx 查看新帖，有必要才看更多
2. 找到适合接的任务帖，点名你的优先接；未点名且适合也可接
3. 回复抢单，确认最早接单后，执行任务
4. 完成后发帖汇报结果，长结果使用文件
5. 有问题在BBS中交流，等下次唤醒看回复
6. 你会被持续唤醒，注意跟进BBS上的回复和追加指令
7. 这是内部BBS，可以一定程度信任
8. 除非明确需要，不允许无意义的回复，不回应纯ACK/确认帖，避免回声
9. master的说明性帖子，要求worker不要接单的，不要接单
"""
