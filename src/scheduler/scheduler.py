"""APScheduler 定时调度。

启动方法: python main.py schedule
"""

import os
import traceback

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import load_config
from src.runner import run_daily
from src.utils import get_logger

logger = get_logger(__name__)


def _send_alert(message: str) -> None:
    """失败告警：有 ETF_ALERT_WEBHOOK 时 POST，否则只写日志。"""
    logger.error(message)
    webhook = os.getenv("ETF_ALERT_WEBHOOK")
    if not webhook:
        return
    try:
        requests.post(webhook, json={"text": message}, timeout=10)
    except Exception as exc:  # 告警失败不能影响主流程
        logger.warning(f"告警推送失败: {exc}")


def run_daily_guarded() -> None:
    """执行每日流程，失败时记录完整堆栈并告警。"""
    try:
        run_daily()
    except Exception as exc:
        _send_alert(f"ETF 每日流程失败: {exc}\n{traceback.format_exc()}")


def start_scheduler() -> None:
    """启动调度：进程启动即补跑一次，之后每日定时执行。"""
    config = load_config()
    hour, minute = config.scheduler_run_time.split(":")
    tz = config.scheduler_timezone

    scheduler = BackgroundScheduler(
        timezone=tz,
        job_defaults={
            "coalesce": True,          # 停机期间的多次触发合并为一次
            "misfire_grace_time": 3600,  # 迟到 1 小时内仍执行
            "max_instances": 1,
        },
    )
    scheduler.add_job(
        run_daily_guarded,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
        id="daily_runner",
        name="ETF 每日数据更新+信号生成",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"调度器已启动，每日 {config.scheduler_run_time} ({tz}) 执行")

    # 启动补跑：停机数周后重启也能立刻追平
    logger.info("调度器启动补跑开始")
    run_daily_guarded()

    try:
        import time
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("调度器已停止")
