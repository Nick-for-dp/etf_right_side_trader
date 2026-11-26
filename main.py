"""ETF 右侧交易助手 — 统一入口。

用法:
    python main.py init                             首次初始化（全部 ETF）
    python main.py init --symbol 588000              单只 ETF 回填
    python main.py init-market --start 2022-01-01    初始化指数行情与市场状态
    python main.py sync-etf-mapping                  同步 settings.yaml 到 etf_mapping
    python main.py backfill-tushare                  Tushare 历史 OHLCV 回填
    python main.py run                               执行一次每日流程（STEP 1-5）
    python main.py schedule                          启动每日 07:00 定时调度
    python main.py dashboard                         启动 Streamlit 仪表盘（默认 18501）
    python main.py check-data                        检查各数据域最新日期与缺口
    python main.py rebuild-signals --start 2024-06-01 --end 2026-06-03
    python main.py backtest-portfolio --start 2016-01-01 --end 2026-06-03
    python main.py backtest-misjudge --start 2016-01-01 --end 2026-06-03
    python main.py backtest-stop-loss --start 2016-01-01 --end 2026-06-03
"""

import argparse
import sys
from datetime import date


def main():
    parser = argparse.ArgumentParser(
        prog="etf-trader",
        description="ETF 右侧交易助手",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="初始化：建表 + 回填数据")
    init_parser.add_argument("--symbol", type=str, default=None,
                             help="单只 ETF 代码，不传则覆盖全部")
    init_parser.add_argument("--start", type=str, default=None,
                             help="回填起始日期 YYYY-MM-DD")

    market_parser = sub.add_parser("init-market", help="初始化指数行情与市场状态")
    market_parser.add_argument("--start", type=str, default=None)
    market_parser.add_argument("--end", type=str, default=None)

    tushare_parser = sub.add_parser("backfill-tushare", help="Tushare 历史 OHLCV 回填")
    tushare_parser.add_argument("--symbol", type=str, default=None)
    tushare_parser.add_argument("--start", type=str, default="20160101")
    tushare_parser.add_argument("--end", type=str, default=None)

    portfolio_parser = sub.add_parser("backtest-portfolio", help="净值口径组合回测（v2.5 limited）")
    portfolio_parser.add_argument("--symbol", type=str, default=None)
    portfolio_parser.add_argument("--start", type=str, default=None)
    portfolio_parser.add_argument("--end", type=str, default=None)
    portfolio_parser.add_argument("--capital", type=float, default=100000.0)
    portfolio_parser.add_argument("--cost", type=float, default=0.0005)
    portfolio_parser.add_argument("--slippage", type=float, default=0.0001)

    misjudge_parser = sub.add_parser("backtest-misjudge", help="亏损交易归因")
    misjudge_parser.add_argument("--symbol", type=str, default=None)
    misjudge_parser.add_argument("--start", type=str, default=None)
    misjudge_parser.add_argument("--end", type=str, default=None)
    misjudge_parser.add_argument("--loss", type=float, default=-0.10,
                                help="亏损阈值，默认 -0.10")

    stop_loss_parser = sub.add_parser("backtest-stop-loss", help="止损事件与止损后走势")
    stop_loss_parser.add_argument("--symbol", type=str, default=None)
    stop_loss_parser.add_argument("--start", type=str, default=None)
    stop_loss_parser.add_argument("--end", type=str, default=None)

    rebuild_parser = sub.add_parser("rebuild-signals", help="按范围删除并重算 signals")
    rebuild_parser.add_argument("--symbol", type=str, default=None)
    rebuild_parser.add_argument("--start", type=str, required=True)
    rebuild_parser.add_argument("--end", type=str, required=True)
    rebuild_parser.add_argument("--dry-run", action="store_true",
                                help="只统计范围，不删除或写入")
    rebuild_parser.add_argument("--skip-advice", action="store_true",
                                help="不重算最新交易日的 operation_advice")

    sub.add_parser("run", help="执行一次每日流程")
    sub.add_parser("schedule", help="启动定时调度")
    dashboard_parser = sub.add_parser("dashboard", help="启动 Streamlit 仪表盘")
    dashboard_parser.add_argument("--port", type=int, default=18501,
                                  help="仪表盘端口，默认 18501")
    sub.add_parser("check-data", help="检查各数据域最新日期与缺口")
    sub.add_parser("sync-etf-mapping", help="同步 settings.yaml ETF 映射到数据库")

    args = parser.parse_args()

    if args.command == "init":
        from init_db import init_system
        start_date = date.fromisoformat(args.start) if args.start else None
        init_system(symbol=args.symbol, start_date=start_date)
    elif args.command == "init-market":
        from init_db import init_market_data
        start_date = date.fromisoformat(args.start) if args.start else None
        end_date = date.fromisoformat(args.end) if args.end else None
        init_market_data(start_date=start_date, end_date=end_date)
    elif args.command == "backfill-tushare":
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        from src.fetcher import DataManager
        from src.service import TradingCalendarService
        config = load_config()
        init_engine(config.db_url)
        calendar = TradingCalendarService()
        dm = DataManager(config, None, calendar)
        dm.backfill_tushare(symbol=args.symbol, start_date=args.start, end_date=args.end)
        dispose_engine()
    elif args.command == "backtest-portfolio":
        from src.backtest.portfolio_backtest import run_portfolio_backtest, format_portfolio_report
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        config = load_config()
        init_engine(config.db_url)
        try:
            result = run_portfolio_backtest(
                codes=[args.symbol] if args.symbol else None,
                start=date.fromisoformat(args.start) if args.start else None,
                end=date.fromisoformat(args.end) if args.end else None,
                capital=args.capital, cost_ratio=args.cost, slippage=args.slippage,
            )
            print(format_portfolio_report(result))
        finally:
            dispose_engine()
    elif args.command == "backtest-misjudge":
        from src.backtest.misjudge_report import run_misjudge_analysis, format_misjudge_report
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        config = load_config()
        init_engine(config.db_url)
        try:
            result = run_misjudge_analysis(
                codes=[args.symbol] if args.symbol else None,
                start=date.fromisoformat(args.start) if args.start else None,
                end=date.fromisoformat(args.end) if args.end else None,
                loss_threshold=args.loss,
            )
            print(format_misjudge_report(result))
        finally:
            dispose_engine()
    elif args.command == "backtest-stop-loss":
        from src.backtest.stop_loss_attribution_report import (
            run_stop_loss_attribution_backtest,
            format_stop_loss_attribution_report,
        )
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        config = load_config()
        init_engine(config.db_url)
        try:
            result = run_stop_loss_attribution_backtest(
                codes=[args.symbol] if args.symbol else None,
                start=date.fromisoformat(args.start) if args.start else None,
                end=date.fromisoformat(args.end) if args.end else None,
            )
            print(format_stop_loss_attribution_report(result))
        finally:
            dispose_engine()
    elif args.command == "rebuild-signals":
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        from src.database.schema_maintenance import ensure_schema
        from src.service.signal_rebuild_service import (
            format_rebuild_signals_report,
            rebuild_signals,
        )
        config = load_config()
        engine = init_engine(config.db_url)
        ensure_schema(engine)
        try:
            result = rebuild_signals(
                config=config,
                start=date.fromisoformat(args.start),
                end=date.fromisoformat(args.end),
                codes=[args.symbol] if args.symbol else None,
                dry_run=args.dry_run,
                rebuild_latest_advice=not args.skip_advice,
            )
            print(format_rebuild_signals_report(result))
        finally:
            dispose_engine()
    elif args.command == "run":
        from src.runner import run_daily
        run_daily()
    elif args.command == "sync-etf-mapping":
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        from src.database.schema import Base
        from src.service.etf_mapping_service import (
            EtfMappingService,
            format_etf_mapping_sync_report,
        )
        config = load_config()
        engine = init_engine(config.db_url)
        try:
            Base.metadata.create_all(engine)
            result = EtfMappingService.sync_from_config(config)
            print(format_etf_mapping_sync_report(result))
        finally:
            dispose_engine()
    elif args.command == "schedule":
        from src.scheduler import start_scheduler
        start_scheduler()
    elif args.command == "check-data":
        from src.database.connection import init_engine, dispose_engine
        from src.database.data_health import check_all
        from src.config import load_config
        config = load_config()
        init_engine(config.db_url)
        check_all(config)
        dispose_engine()
    elif args.command == "dashboard":
        import subprocess
        # 明确指定端口，避免 Streamlit 从被系统保留的端口段自动探测失败。
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            "src/dashboard/app.py",
            "--server.headless", "true",
            "--server.port", str(args.port),
        ])


if __name__ == "__main__":
    main()
