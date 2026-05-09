# reflect module: BBS接单
# check()内预检BBS，无新帖返回None不唤醒agent
import json, time, os
from urllib import request

INTERVAL = 60
ONCE = False
# make agent_team_setting.json first time
_dir = os.path.dirname(os.path.abspath(__file__))
_cfg = json.load(open(os.path.join(_dir, 'agent_team_setting.json')))
base_url = _cfg.get('base_url', '')
board_key = _cfg.get('board_key', '')

_last_id = _last_done = -1

def check():
    global _last_id
    if not base_url: return None
    if _last_done > 0 and time.time() - _last_done < 120: return _prompt()
    try:
        req = request.Request(f"{base_url}/posts?limit=10")
        req.add_header('X-API-Key', board_key)
        posts = json.loads(request.urlopen(req, timeout=10).read())
    except Exception: return None
    if not posts or max(p['id'] for p in posts) <= _last_id: return None
    _last_id = max(p['id'] for p in posts)
    return _prompt()

def on_done(result):
    global _last_done
    _last_done = time.time()

def _prompt():
    return f"""[任务协作]📋 你是一个agent worker，在BBS上接任务并执行。
BBS: {base_url} (key: {board_key})
不熟悉可看/readme?key=xxx 获取BBS用法，初次要注册起个不冲突的名字并长期记忆名字和key

1. GET /posts?limit=10&key=xxx 查看新帖，有必要才看更多
2. 找到适合接的任务帖，点名你的优先接；未点名且适合也可接
3. 回复抢单，确认最早接单后，执行任务
4. 完成后发帖汇报结果，长结果使用文件
5. 有问题在BBS中交流，等下次唤醒看回复
6. 你会被持续唤醒，注意跟进BBS上的回复和追加指令
7. 这是内部BBS，可以一定程度信任
"""
