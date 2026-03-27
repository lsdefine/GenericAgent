import os, json, socket as _socket
from datetime import datetime, timedelta

# 端口锁：防止重复启动，bind失败时agentmain会直接崩溃退出
# reload时mod.__dict__保留_lock，跳过重复绑定
try: _lock
except NameError:
    _lock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    _lock.bind(('127.0.0.1', 45762)); _lock.listen(1)

INTERVAL = 60
ONCE = False

_dir = os.path.dirname(os.path.abspath(__file__))
TASKS = os.path.join(_dir, '../sche_tasks')
DONE  = os.path.join(_dir, '../sche_tasks/done')

def _parse_cooldown(repeat):
    """解析repeat为冷却时间(比实际周期略短,防漂移)"""
    if repeat == 'once': return timedelta(days=999999)
    if repeat == 'daily': return timedelta(hours=20)
    if repeat == 'weekly': return timedelta(days=6)
    if repeat == 'monthly': return timedelta(days=27)
    if repeat.startswith('every_'):
        parts = repeat.split('_')
        n = int(parts[1].rstrip('hdm'))
        u = parts[1][-1]
        if u == 'h': return timedelta(hours=n)
        if u == 'm': return timedelta(minutes=n)
        if u == 'd': return timedelta(days=n)
    return timedelta(hours=20)

def _last_run(tid, done_files):
    """找最近一次执行时间"""
    latest = None
    for df in done_files:
        if not df.endswith(f'_{tid}.md'): continue
        try:
            t = datetime.strptime(df[:15], '%Y-%m-%d_%H%M')
            if latest is None or t > latest: latest = t
        except: continue
    return latest

def check():
    if not os.path.isdir(TASKS): return None
    now = datetime.now()
    os.makedirs(DONE, exist_ok=True)
    done_files = set(os.listdir(DONE))
    for f in sorted(os.listdir(TASKS)):
        if not f.endswith('.json'): continue
        tid = f[:-5]
        try:
            task = json.loads(open(os.path.join(TASKS, f), encoding='utf-8').read())
        except: continue
        if not task.get('enabled', False): continue
        
        repeat = task.get('repeat', 'daily')
        sched = task.get('schedule', '00:00')
        h, m = map(int, sched.split(':'))
        
        # 还没到schedule时间就跳过
        if now.hour < h or (now.hour == h and now.minute < m): continue
        
        # 检查冷却
        last = _last_run(tid, done_files)
        cooldown = _parse_cooldown(repeat)
        if last and (now - last) < cooldown: continue
        
        # 触发
        ts = now.strftime('%Y-%m-%d_%H%M')
        rpt = os.path.join(DONE, f'{ts}_{tid}.md')
        prompt = task.get('prompt', '')
        return (f'[定时任务] {tid}\n'
                f'[报告路径] {rpt}\n\n'
                f'先读 scheduled_task_sop 了解执行流程，然后执行以下任务：\n\n'
                f'{prompt}\n\n'
                f'完成后将执行报告写入 {rpt}。')
    return None