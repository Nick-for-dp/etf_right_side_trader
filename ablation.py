"""消融实验入口。

生产入口保持在 main.py；策略消融和候选矩阵实验集中放在本文件。

用法:
    python ablation.py --start 2016-01-01
    python ablation.py --matrix entry-add-budget --start 2016-01-01
    python ablation.py --matrix stop-loss-by-segment --start 2016-01-01
    python ablation.py --matrix candidate-comparison
    python ablation.py --matrix relative-strength --start 2016-01-01
"""

import argparse
from datetime import date


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="etf-ablation",
        description="ETF 右侧交易助手消融实验入口",
    )
    parser.add_argument(
        "--symbol", type=str, default=None,
        help="单只 ETF 代码，不传则覆盖全部配置 ETF",
    )
    parser.add_argument(
        "--start", type=str, default=None,
        help="回测起始日期 YYYY-MM-DD，不传则按实验默认口径",
    )
    parser.add_argument(
        "--end", type=str, default=None,
        help="回测结束日期 YYYY-MM-DD，不传则为昨天",
    )
    parser.add_argument(
        "--capital", type=float, default=100000.0,
        help="初始资金，默认 100000",
    )
    parser.add_argument(
        "--cost", type=float, default=0.0005,
        help="佣金率，默认 0.0005（万分之五）",
    )
    parser.add_argument(
        "--slippage", type=float, default=0.0001,
        help="滑点率，默认 0.0001（万分之一）",
    )
    parser.add_argument(
        "--matrix", type=str, default="default",
        choices=[
            "default",
            "preferred-cycle",
            "add-rules",
            "entry-add-budget",
            "stop-loss-rules",
            "stop-loss-by-segment",
            "candidate-comparison",
            "reentry-rules",
            "trend-reentry-segments",
            "high-vol-reentry-cooldown",
            "high-vol-reentry-stop-price",
            "relative-strength",
        ],
        help=(
            "消融实验集：default、preferred-cycle、add-rules、"
            "entry-add-budget、stop-loss-rules、stop-loss-by-segment、"
            "candidate-comparison、reentry-rules、trend-reentry-segments、"
            "high-vol-reentry-cooldown、high-vol-reentry-stop-price "
            "或 relative-strength，默认 default"
        ),
    )

    args = parser.parse_args()

    from src.backtest.ablation_report import (
        format_ablation_report,
        format_candidate_comparison_report,
        format_high_vol_reentry_cooldown_report,
        format_high_vol_reentry_stop_price_report,
        format_reentry_rules_report,
        format_segmented_stop_loss_report,
        format_trend_reentry_segments_report,
        run_ablation_backtest,
        run_candidate_comparison_backtest,
        run_high_vol_reentry_cooldown_backtest,
        run_high_vol_reentry_stop_price_backtest,
        run_reentry_rules_backtest,
        run_segmented_stop_loss_backtest,
        run_trend_reentry_segments_backtest,
    )
    from src.config import load_config
    from src.database import dispose_engine, init_engine
    from src.backtest.relative_strength_report import (
        format_relative_strength_report,
        run_relative_strength_backtest,
    )

    config = load_config()
    init_engine(config.db_url)
    try:
        codes = [args.symbol] if args.symbol else None
        start_date = date.fromisoformat(args.start) if args.start else None
        end_date = date.fromisoformat(args.end) if args.end else None

        if args.matrix == "relative-strength":
            result = run_relative_strength_backtest(
                codes=codes,
                start=start_date,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_relative_strength_report(result))
        elif args.matrix == "stop-loss-by-segment":
            result = run_segmented_stop_loss_backtest(
                codes=codes,
                start=start_date,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_segmented_stop_loss_report(result))
        elif args.matrix == "candidate-comparison":
            result = run_candidate_comparison_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_candidate_comparison_report(result))
        elif args.matrix == "reentry-rules":
            result = run_reentry_rules_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_reentry_rules_report(result))
        elif args.matrix == "trend-reentry-segments":
            result = run_trend_reentry_segments_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_trend_reentry_segments_report(result))
        elif args.matrix == "high-vol-reentry-cooldown":
            result = run_high_vol_reentry_cooldown_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_high_vol_reentry_cooldown_report(result))
        elif args.matrix == "high-vol-reentry-stop-price":
            result = run_high_vol_reentry_stop_price_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_high_vol_reentry_stop_price_report(result))
        else:
            result = run_ablation_backtest(
                codes=codes,
                start=start_date,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
                matrix=args.matrix,
            )
            print(format_ablation_report(result))
    finally:
        dispose_engine()


if __name__ == "__main__":
    main()
