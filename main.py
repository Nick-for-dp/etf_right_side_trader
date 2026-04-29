"""ETF 右侧交易助手 — 统一入口。

用法:
    python main.py init       首次初始化（建表 + 回填行情 + 计算指标 + 生成信号）
    python main.py run        执行一次每日流程（STEP 1-5）
    python main.py schedule   启动每日 07:00 定时调度
    python main.py dashboard  启动 Streamlit 仪表盘
"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="etf-trader",
        description="ETF 右侧交易助手",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="首次初始化：建表 + 回填数据")
    sub.add_parser("run", help="执行一次每日流程")
    sub.add_parser("schedule", help="启动定时调度")
    sub.add_parser("dashboard", help="启动 Streamlit 仪表盘")

    args = parser.parse_args()

    if args.command == "init":
        from init_db import init_system
        init_system()
    elif args.command == "run":
        from src.runner import run_daily
        run_daily()
    elif args.command == "schedule":
        from src.scheduler import start_scheduler
        start_scheduler()
    elif args.command == "dashboard":
        import subprocess
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            "src/dashboard/app.py",
            "--server.headless", "true",
        ])


if __name__ == "__main__":
    main()
