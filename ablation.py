"""消融实验入口。

生产入口保持在 main.py；策略消融和候选矩阵实验集中放在本文件。

用法:
    python ablation.py --start 2016-01-01
    python ablation.py --matrix entry-add-budget --start 2016-01-01
    python ablation.py --matrix stop-loss-by-segment --start 2016-01-01
    python ablation.py --matrix candidate-comparison
    python ablation.py --matrix relative-strength --start 2016-01-01
    python ablation.py --matrix volatility-strategy --start 2016-01-01
    python ablation.py --matrix volatility-profile-strategy --start 2016-01-01
    python ablation.py --matrix high-vol-mixed-strategy
    python ablation.py --matrix high-vol-frequency-control
    python ablation.py --matrix high-vol-quality-control
    python ablation.py --matrix high-vol-quality-tier-robustness
    python ablation.py --matrix high-vol-quality-capital-attribution
    python ablation.py --matrix volatility-focus-anchor
    python ablation.py --matrix volatility-profile-validation
    python ablation.py --matrix portfolio-risk-control
    python ablation.py --matrix stop-loss-attribution
    python ablation.py --matrix etf-tier-classification
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
            "volatility-strategy",
            "volatility-profile-strategy",
            "high-vol-mixed-strategy",
            "high-vol-frequency-control",
            "high-vol-quality-control",
            "high-vol-quality-tier-robustness",
            "high-vol-quality-capital-attribution",
            "volatility-focus-anchor",
            "volatility-profile-validation",
            "portfolio-risk-control",
            "stop-loss-attribution",
            "etf-tier-classification",
        ],
        help=(
            "消融实验集：default、preferred-cycle、add-rules、"
            "entry-add-budget、stop-loss-rules、stop-loss-by-segment、"
            "candidate-comparison、reentry-rules、trend-reentry-segments、"
            "high-vol-reentry-cooldown、high-vol-reentry-stop-price "
            "relative-strength、volatility-strategy 或 "
            "volatility-profile-strategy、high-vol-mixed-strategy、"
            "high-vol-frequency-control、high-vol-quality-control、"
            "high-vol-quality-tier-robustness、"
            "high-vol-quality-capital-attribution、volatility-focus-anchor、"
            "volatility-profile-validation、"
            "portfolio-risk-control、stop-loss-attribution、"
            "etf-tier-classification，默认 default"
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
    from src.backtest.volatility_strategy_report import (
        format_volatility_strategy_report,
        run_volatility_strategy_backtest,
    )
    from src.backtest.volatility_profile_strategy_report import (
        format_volatility_profile_strategy_report,
        run_volatility_profile_strategy_backtest,
    )
    from src.backtest.high_vol_mixed_strategy_report import (
        format_high_vol_mixed_strategy_report,
        run_high_vol_mixed_strategy_backtest,
    )
    from src.backtest.high_vol_frequency_control_report import (
        format_high_vol_frequency_control_report,
        run_high_vol_frequency_control_backtest,
    )
    from src.backtest.high_vol_quality_control_report import (
        format_high_vol_quality_control_report,
        run_high_vol_quality_control_backtest,
    )
    from src.backtest.high_vol_quality_tier_robustness_report import (
        format_high_vol_quality_tier_robustness_report,
        run_high_vol_quality_tier_robustness_backtest,
    )
    from src.backtest.high_vol_quality_capital_attribution_report import (
        format_high_vol_quality_capital_attribution_report,
        run_high_vol_quality_capital_attribution_backtest,
    )
    from src.backtest.volatility_focus_anchor_report import (
        format_volatility_focus_anchor_report,
        run_volatility_focus_anchor_backtest,
    )
    from src.backtest.volatility_profile_validation_report import (
        format_volatility_profile_validation_report,
        run_volatility_profile_validation_backtest,
    )
    from src.backtest.portfolio_risk_control_report import (
        format_portfolio_risk_control_report,
        run_portfolio_risk_control_backtest,
    )
    from src.backtest.stop_loss_attribution_report import (
        format_stop_loss_attribution_report,
        run_stop_loss_attribution_backtest,
    )
    from src.backtest.etf_tier_classification_report import (
        format_etf_tier_classification_report,
        run_etf_tier_classification_backtest,
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
        elif args.matrix == "volatility-strategy":
            result = run_volatility_strategy_backtest(
                codes=codes,
                start=start_date,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_volatility_strategy_report(result))
        elif args.matrix == "volatility-profile-strategy":
            result = run_volatility_profile_strategy_backtest(
                codes=codes,
                start=start_date,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_volatility_profile_strategy_report(result))
        elif args.matrix == "high-vol-mixed-strategy":
            result = run_high_vol_mixed_strategy_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_high_vol_mixed_strategy_report(result))
        elif args.matrix == "high-vol-frequency-control":
            result = run_high_vol_frequency_control_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_high_vol_frequency_control_report(result))
        elif args.matrix == "high-vol-quality-control":
            result = run_high_vol_quality_control_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_high_vol_quality_control_report(result))
        elif args.matrix == "high-vol-quality-tier-robustness":
            result = run_high_vol_quality_tier_robustness_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_high_vol_quality_tier_robustness_report(result))
        elif args.matrix == "high-vol-quality-capital-attribution":
            result = run_high_vol_quality_capital_attribution_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_high_vol_quality_capital_attribution_report(result))
        elif args.matrix == "volatility-focus-anchor":
            result = run_volatility_focus_anchor_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_volatility_focus_anchor_report(result))
        elif args.matrix == "volatility-profile-validation":
            result = run_volatility_profile_validation_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_volatility_profile_validation_report(result))
        elif args.matrix == "portfolio-risk-control":
            result = run_portfolio_risk_control_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_portfolio_risk_control_report(result))
        elif args.matrix == "stop-loss-attribution":
            result = run_stop_loss_attribution_backtest(
                codes=codes,
                start=start_date,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_stop_loss_attribution_report(result))
        elif args.matrix == "etf-tier-classification":
            result = run_etf_tier_classification_backtest(
                codes=codes,
                end=end_date,
                capital=args.capital,
                cost_ratio=args.cost,
                slippage=args.slippage,
            )
            print(format_etf_tier_classification_report(result))
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
