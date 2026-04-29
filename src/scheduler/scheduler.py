"""APScheduler 定时调度。

启动方法: python run_scheduler.py
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import load_config
from src.runner import run_daily
from src.utils import get_logger

logger = get_logger(__name__)


def start_scheduler() -> None:
    """创建 APScheduler 实例，注册每日 run_daily 任务，启动调度循环。

    Returns:
        None

    Example:
        >>> start_scheduler()  # 阻塞运行，按 Ctrl+C 退出
    """
    config = load_config()
    hour, minute = config.scheduler_run_time.split(":")
    tz = config.scheduler_timezone

    scheduler = BackgroundScheduler(timezone=tz)
    trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)
    scheduler.add_job(
        run_daily,
        trigger=trigger,
        id="daily_runner",
        name="ETF 每日数据更新+信号生成",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"调度器已启动，每日 {config.scheduler_run_time} ({tz}) 执行")

    try:
        # 保持主线程存活，让后台调度器持续运行
        import time
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("调度器已停止")
