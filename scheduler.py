# ══════════════════════════════════════════════════════════════════════════════
#  aduAgent — scheduler.py (APScheduler 3.11.2 + zoneinfo CST)
# ══════════════════════════════════════════════════════════════════════════════
import logging
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger("adu.scheduler")
CST = ZoneInfo("Asia/Shanghai")  # 物理时区锁死

_scheduler: BackgroundScheduler | None = None

def start_scheduler(enqueue_callback):
    """
    挂载起搏器。每天早 8 点晨报。
    enqueue_callback: 接收 job 入队逻辑的回调，签名 enqueue_callback()
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone=CST)

    _scheduler.add_job(
        enqueue_callback,
        trigger=CronTrigger(hour=8, minute=0, timezone=CST),
        id="daily_morning_report",
        replace_existing=True,
    )

    _scheduler.start()
    print("\n=== 💓 教授调度器激活 ===")
    _scheduler.print_jobs()  # 必须触发此行，留下 CST+0800 证据
    print("==========================\n")
    return _scheduler
