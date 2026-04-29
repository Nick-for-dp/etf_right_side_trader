"""定时任务入口：python run_scheduler.py

启动 APScheduler，按 settings.yaml 中的 cron 配置自动执行。
"""

from src.scheduler.scheduler import start_scheduler

if __name__ == "__main__":
    start_scheduler()
