"""手动运行入口：python daily_runner.py

执行单次全流程，供调试和补跑使用。
"""

from src.runner.daily_runner import run_daily

if __name__ == "__main__":
    run_daily()
