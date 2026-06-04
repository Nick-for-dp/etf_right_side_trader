"""ETF 右侧交易助手 — 统一入口。

用法:
    python main.py init                          首次初始化（全量 ETF）
    python main.py init --symbol 588000          增量回填单只 ETF
    python main.py init --symbol 588000 --start 2024-01-01
    python main.py init-market --start 2022-01-01  初始化指数历史行情和市场热度
    python main.py backfill-tushare              Tushare 历史 OHLCV 回填（临时，全量 ETF）
    python main.py backfill-tushare --symbol 588000 --start 20200101
    python main.py run                           执行一次每日流程（STEP 1-5）
    python main.py schedule                      启动每日 07:00 定时调度
    python main.py dashboard                     启动 Streamlit 仪表盘
    python main.py backtest-odds                  V2.0 vs V2.1A vs V2.2-market 回测对比
    python main.py backtest-odds --symbol 588000  单只 ETF 回测试算
    python main.py rebuild-signals --start 2024-06-01 --end 2026-06-03
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
    init_parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码（如 588000），不传则覆盖全部 ETF",
    )
    init_parser.add_argument(
        "--start", type=str, default=None,
        help="回填起始日期 YYYY-MM-DD，不传则按 lookback_days 推算",
    )

    market_parser = sub.add_parser(
        "init-market",
        help="初始化指数历史行情和市场热度",
    )
    market_parser.add_argument(
        "--start", type=str, default=None,
        help="起始日期 YYYY-MM-DD，不传则按 lookback_days 推算",
    )
    market_parser.add_argument(
        "--end", type=str, default=None,
        help="截止日期 YYYY-MM-DD，不传则为 T-1",
    )

    # 临时命令：Tushare 历史回填（token 过期前使用）
    tushare_parser = sub.add_parser(
        "backfill-tushare",
        help="Tushare 历史 OHLCV 回填（临时，不拉 NAV）",
    )
    tushare_parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码，不传则覆盖全部配置 ETF",
    )
    tushare_parser.add_argument(
        "--start", type=str, default="20180101",
        help="起始日期 YYYYMMDD，默认 20180101",
    )
    tushare_parser.add_argument(
        "--end", type=str, default=None,
        help="截止日期 YYYYMMDD，默认 T-1",
    )

    # 赔率门控回测对比
    backtest_parser = sub.add_parser("backtest-odds", help="V2.0 vs V2.1A vs V2.2-market 回测对比")
    backtest_parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码，不传则覆盖全部配置 ETF",
    )
    backtest_parser.add_argument(
        "--start", type=str, default=None,
        help="回测起始日期 YYYY-MM-DD，不传则自动推算（最早信号日期）",
    )
    backtest_parser.add_argument(
        "--end", type=str, default=None,
        help="回测结束日期 YYYY-MM-DD，不传则为昨天",
    )

    misjudge_parser = sub.add_parser("backtest-misjudge", help="买卖误判分析（亏损交易归因）")
    misjudge_parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码，不传则覆盖全部",
    )
    misjudge_parser.add_argument(
        "--start", type=str, default=None,
    )
    misjudge_parser.add_argument(
        "--end", type=str, default=None,
    )
    misjudge_parser.add_argument(
        "--loss", type=float, default=-0.10,
        help="亏损阈值，默认 -0.10（-10%）",
    )

    attribution_parser = sub.add_parser("backtest-attribution", help="市场热度拦截归因分析")
    attribution_parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码，不传则覆盖全部配置 ETF",
    )
    attribution_parser.add_argument(
        "--start", type=str, default=None,
        help="起始日期 YYYY-MM-DD",
    )
    attribution_parser.add_argument(
        "--end", type=str, default=None,
        help="结束日期 YYYY-MM-DD",
    )

    portfolio_parser = sub.add_parser("backtest-portfolio", help="净值口径回测对比（v2.0/v2.1A/v2.2）")
    portfolio_parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码，不传则覆盖全部配置 ETF",
    )
    portfolio_parser.add_argument(
        "--start", type=str, default=None,
        help="回测起始日期 YYYY-MM-DD，不传则按 lookback_days 推算",
    )
    portfolio_parser.add_argument(
        "--end", type=str, default=None,
        help="回测结束日期 YYYY-MM-DD，不传则为昨天",
    )
    portfolio_parser.add_argument(
        "--capital", type=float, default=100000.0,
        help="初始资金，默认 100000",
    )
    portfolio_parser.add_argument(
        "--cost", type=float, default=0.0005,
        help="佣金率，默认 0.0005（万分之五）",
    )

    rebuild_signals_parser = sub.add_parser(
        "rebuild-signals",
        help="按范围删除并重算 signals（不改 quote/indicators）",
    )
    rebuild_signals_parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码，不传则覆盖全部配置 ETF",
    )
    rebuild_signals_parser.add_argument(
        "--start", type=str, required=True,
        help="重算起始日期 YYYY-MM-DD",
    )
    rebuild_signals_parser.add_argument(
        "--end", type=str, required=True,
        help="重算截止日期 YYYY-MM-DD",
    )
    rebuild_signals_parser.add_argument(
        "--dry-run", action="store_true",
        help="只统计将要重算的范围，不删除或写入",
    )
    rebuild_signals_parser.add_argument(
        "--skip-advice", action="store_true",
        help="不重算区间内最新交易日的 operation_advice",
    )

    sub.add_parser("run", help="执行一次每日流程")
    sub.add_parser("schedule", help="启动定时调度")
    sub.add_parser("dashboard", help="启动 Streamlit 仪表盘")
    sub.add_parser("check-data", help="检查各数据域最新日期、缺失数和异常")

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
        dm = DataManager(config, None, calendar)  # fetcher 不使用，Tushare 内部自建
        dm.backfill_tushare(
            symbol=args.symbol,
            start_date=args.start,
            end_date=args.end,
        )
        dispose_engine()
    elif args.command == "backtest-odds":
        from src.backtest import run_odds_gate_backtest, format_comparison_report
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        config = load_config()
        init_engine(config.db_url)
        try:
            codes = [args.symbol] if args.symbol else None
            start_date = date.fromisoformat(args.start) if args.start else None
            end_date = date.fromisoformat(args.end) if args.end else None
            result = run_odds_gate_backtest(codes=codes, start=start_date, end=end_date)
            report = format_comparison_report(result)
            print(report)
        finally:
            dispose_engine()
    elif args.command == "backtest-misjudge":
        from src.backtest.misjudge_report import run_misjudge_analysis, format_misjudge_report
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        config = load_config()
        init_engine(config.db_url)
        try:
            codes = [args.symbol] if args.symbol else None
            start_date = date.fromisoformat(args.start) if args.start else None
            end_date = date.fromisoformat(args.end) if args.end else None
            result = run_misjudge_analysis(
                codes=codes, start=start_date, end=end_date,
                loss_threshold=args.loss,
            )
            print(format_misjudge_report(result))
        finally:
            dispose_engine()
    elif args.command == "backtest-attribution":
        from src.backtest.attribution_report import run_attribution, format_attribution_report
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        config = load_config()
        init_engine(config.db_url)
        try:
            codes = [args.symbol] if args.symbol else None
            start_date = date.fromisoformat(args.start) if args.start else None
            end_date = date.fromisoformat(args.end) if args.end else None
            result = run_attribution(codes=codes, start=start_date, end=end_date)
            print(format_attribution_report(result))
        finally:
            dispose_engine()
    elif args.command == "backtest-portfolio":
        from src.backtest.portfolio_backtest import run_portfolio_backtest, format_portfolio_report
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        config = load_config()
        init_engine(config.db_url)
        try:
            codes = [args.symbol] if args.symbol else None
            start_date = date.fromisoformat(args.start) if args.start else None
            end_date = date.fromisoformat(args.end) if args.end else None
            result = run_portfolio_backtest(
                codes=codes, start=start_date, end=end_date,
                capital=args.capital, cost_ratio=args.cost,
            )
            print(format_portfolio_report(result))
        finally:
            dispose_engine()
    elif args.command == "rebuild-signals":
        from src.config import load_config
        from src.database import init_engine, dispose_engine
        from src.service.signal_rebuild_service import (
            format_rebuild_signals_report,
            rebuild_signals,
        )
        config = load_config()
        init_engine(config.db_url)
        try:
            codes = [args.symbol] if args.symbol else None
            result = rebuild_signals(
                config=config,
                start=date.fromisoformat(args.start),
                end=date.fromisoformat(args.end),
                codes=codes,
                dry_run=args.dry_run,
                rebuild_latest_advice=not args.skip_advice,
            )
            print(format_rebuild_signals_report(result))
        finally:
            dispose_engine()
    elif args.command == "run":
        from src.runner import run_daily
        run_daily()
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
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            "src/dashboard/app.py",
            "--server.headless", "true",
        ])


if __name__ == "__main__":
    main()
