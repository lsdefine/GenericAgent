import os, json, time as _time, socket as _socket, logging
from datetime import datetime, timedelta

# 端口锁：防止重复启动，bind失败时agentmain会直接崩溃退出
# reload时mod.__dict__保留_lock，跳过重复绑定
try: _lock
except NameError:
    _lock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    _lock.bind(('127.0.0.1', 45762)); _lock.listen(1)

INTERVAL = 120
ONCE = False

_dir = os.path.dirname(os.path.abspath(__file__))
TASKS = os.path.join(_dir, '../sche_tasks')
DONE  = os.path.join(_dir, '../sche_tasks/done')
_LOG  = os.path.join(_dir, '../sche_tasks/scheduler.log')

# --- 日志 ---
_logger = logging.getLogger('scheduler')
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _fh = logging.FileHandler(_LOG, encoding='utf-8')
    _fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s',
                                        datefmt='%Y-%m-%d %H:%M'))
    _logger.addHandler(_fh)

# 默认最大延迟窗口（小时），超过此时间不触发
DEFAULT_MAX_DELAY = 6
_l4_t = 0  # last L4 archive time

def _parse_cooldown(repeat):
    """解析repeat为冷却时间(比实际周期略短,防漂移)"""
    if repeat == 'once': return timedelta(days=999999)
    if repeat in ('daily', 'weekday'): return timedelta(hours=20)
    if repeat == 'weekly': return timedelta(days=6)
    if repeat == 'monthly': return timedelta(days=27)
    if repeat.startswith('every_'):
        parts = repeat.split('_')
        n = int(parts[1].rstrip('hdm'))
        u = parts[1][-1]
        if u == 'h': return timedelta(hours=n)
        if u == 'm': return timedelta(minutes=n)
        if u == 'd': return timedelta(days=n)
    _logger.warning(f'Unknown repeat type: {repeat}, fallback to 20h cooldown')
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
    # L4 archive cron (silent, every 12h)
    global _l4_t
    if _time.time() - _l4_t > 43200:
        _l4_t = _time.time()
        try:
            import sys; sys.path.insert(0, os.path.join(_dir, '../memory/L4_raw_sessions'))
            from compress_session import batch_process
            r = batch_process(dry_run=False)
            print(f'[L4 cron] {r}')
        except Exception as e:
            _logger.error(f'L4 archive failed: {e}')

    if not os.path.isdir(TASKS): return None
    now = datetime.now()
    os.makedirs(DONE, exist_ok=True)
    done_files = set(os.listdir(DONE))
    for f in sorted(os.listdir(TASKS)):
        if not f.endswith('.json'): continue
        tid = f[:-5]
        try:
            task = json.loads(open(os.path.join(TASKS, f), encoding='utf-8').read())
        except Exception as e:
            _logger.error(f'JSON parse error for {f}: {e}')
            continue
        if not task.get('enabled', False): continue
        
        repeat = task.get('repeat', 'daily')
        sched = task.get('schedule', '00:00')
        try:
            h, m = map(int, sched.split(':'))
        except Exception as e:
            _logger.error(f'Invalid schedule format in {f}: {sched!r} ({e})')
            continue
        
        # weekday任务：周末跳过
        if repeat == 'weekday' and now.weekday() >= 5: continue
        
        # 还没到schedule时间就跳过
        if now.hour < h or (now.hour == h and now.minute < m): continue
        
        # 执行窗口检查：超过max_delay小时则跳过（防止开机太晚触发过时任务）
        max_delay = task.get('max_delay_hours', DEFAULT_MAX_DELAY)
        sched_minutes = h * 60 + m
        now_minutes = now.hour * 60 + now.minute
        if (now_minutes - sched_minutes) > max_delay * 60:
            _logger.info(f'SKIP {tid}: {now_minutes - sched_minutes}min past schedule, '
                         f'exceeds max_delay={max_delay}h')
            continue
        
        # 检查冷却
        last = _last_run(tid, done_files)
        cooldown = _parse_cooldown(repeat)
        if last and (now - last) < cooldown: continue
        
        # 触发
        _logger.info(f'TRIGGER {tid} (repeat={repeat}, schedule={sched}, '
                     f'last_run={last})')
        ts = now.strftime('%Y-%m-%d_%H%M')
        rpt = os.path.join(DONE, f'{ts}_{tid}.md')
        prompt = task.get('prompt', '')
        return (f'[定时任务] {tid}\n'
                f'[报告路径] {rpt}\n\n'
                f'先读 scheduled_task_sop 了解执行流程，然后执行以下任务：\n\n'
                f'{prompt}\n\n'
                f'完成后将执行报告写入 {rpt}。')

    return None
