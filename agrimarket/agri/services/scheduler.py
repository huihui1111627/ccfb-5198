"""APScheduler 定时采集（与 Web 控制台同进程，也可独立 CLI 跑）。"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import today
from ..db import get_conn, get_setting
from .runner import collect_all

log = logging.getLogger("agri.scheduler")
_scheduler: BackgroundScheduler | None = None


def job_collect() -> None:
    log.info("定时采集开始: %s", today().isoformat())
    try:
        results = collect_all()
        for r in results:
            log.info("采集结果 %s %s: %s (%s)", r.market_code, r.quote_date, r.status, r.message)
    except Exception:
        log.exception("定时采集异常")


def start_scheduler(db_path: str | None = None) -> BackgroundScheduler:
    """按 settings 里的时刻启动每日任务；重复调用只返回已有实例。"""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    with get_conn(db_path) as conn:
        enabled = get_setting(conn, "scheduler_enabled", "1") == "1"
        hour = int(get_setting(conn, "scheduler_hour", "18"))
        minute = int(get_setting(conn, "scheduler_minute", "0"))

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    if enabled:
        sched.add_job(
            job_collect, CronTrigger(hour=hour, minute=minute),
            id="daily_collect", replace_existing=True,
        )
    sched.start()
    _scheduler = sched
    log.info("调度器已启动（%s，每天 %02d:%02d）", "启用" if enabled else "停用", hour, minute)
    return sched


def reload_scheduler(db_path: str | None = None) -> BackgroundScheduler:
    """设置页改了时刻/开关后重建任务。"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    return start_scheduler(db_path)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
