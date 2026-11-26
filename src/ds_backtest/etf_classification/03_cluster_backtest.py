#!/usr/bin/env python
"""按聚类分组独立回测 baseline-v2.4，验证组间策略表现差异。

读入 cluster_labels.json 的分组标签，对每个分组独立跑回测，
对比组间的年化/回撤/胜率/止损/信号质量。
"""

import sys
import os
import json
from datetime import date

import numpy as np

_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.backtest.ablation_config import (
    AblationExperimentConfig,
    BUDGET_RULE_70_15_15_LADDER,
    MONTHLY_QUARTER_90D,
    STOP_LOSS_FIXED_8,
)
from src.backtest.portfolio_backtest import PortfolioBacktest
from src.config import load_config
from src.database import init_engine, dispose_engine
from src.database.repository import indicators_repo
from src.service.calendar_service import TradingCalendarService


CLUSTER_PATH = os.path.join(os.path.dirname(__file__), "cluster_labels.json")
OUT_DIR = os.path.dirname(__file__)

# 分组的中文名称和颜色
CLUSTER_NAMES = {
    0: "主流波动(18只)",
    1: "低波稳健(8只)",
    2: "异常值-机器人(1只)",
}


def main():
    with open(CLUSTER_PATH) as f:
        cluster_labels = json.load(f)

    config = load_config()
    engine = init_engine(config.db_url)
    calendar = TradingCalendarService()
    end = date.fromisoformat(calendar.get_previous_trading_day())

    code_regime_groups = {e.symbol: e.regime_group for e in config.etf_list}
    code_stop_loss_profiles = {e.symbol: e.stop_loss_profile for e in config.etf_list}
    code_volatility_groups = {e.symbol: e.volatility_group for e in config.etf_list}

    # 按聚类分组
    clusters: dict[int, list[str]] = {}
    for code, cid in cluster_labels.items():
        clusters.setdefault(int(cid), []).append(code)

    # 同一窗口对所有分组回测
    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]

    # 统一基线实验配置
    exp = AblationExperimentConfig(
        name="baseline_v2_4",
        label="baseline-v2.4",
        reentry_rule=None,
        max_holding_days=90,
        cycle_profile=MONTHLY_QUARTER_90D,
        entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
        stop_loss_rule=STOP_LOSS_FIXED_8,
        use_config_stop_loss_profiles=True,
    )

    all_rows = []
    for window_label, start, w_end in windows:
        print(f"\n{'='*80}")
        print(f"  窗口: {window_label} ({start} ~ {w_end})")
        print(f"{'='*80}")

        for cid in sorted(clusters.keys()):
            codes = clusters[cid]
            name = CLUSTER_NAMES.get(cid, f"Cluster {cid}")

            bt = PortfolioBacktest(
                calendar=calendar,
                initial_capital=100_000,
                cost_ratio=0.0005,
                slippage=0.0001,
                position_limit=0.3,
                cooldown_days=config.strategy_params.get("cooldown_days", 5),
                market_regime_params=config.market_regime_params,
                code_regime_groups=code_regime_groups,
                code_stop_loss_profiles=code_stop_loss_profiles,
                code_volatility_groups=code_volatility_groups,
            )

            result = bt.run_experiments(
                codes=codes, start=start, end=w_end, experiments=[exp],
            )

            # 提取指标
            version_data = result.get("versions", {}).get("baseline_v2_4", {})
            summary = version_data.get("summary", {})
            stats = version_data.get("stats", {})
            trades = version_data.get("trades", [])

            # 计算信号质量指标
            signals_analyzed = _analyze_signals(codes, start, w_end)

            # 计算持有期统计
            holding_win, holding_loss = _holding_win_rate(trades)

            row = {
                "window": window_label,
                "cluster": cid,
                "cluster_name": name,
                "etf_count": len(codes),
                "etf_list": ",".join(codes),
                "annual_return": summary.get("annual_return", "N/A"),
                "max_drawdown": summary.get("max_drawdown", "N/A"),
                "calmar": summary.get("calmar", "N/A"),
                "sharpe": summary.get("sharpe", "N/A"),
                "win_rate": summary.get("win_rate", "N/A"),
                "profit_factor": summary.get("profit_factor", "N/A"),
                "total_trades": int(summary.get("total_trades", 0) or 0),
                "stop_loss_triggered": int(stats.get("stop_loss_triggered", 0) or 0),
                "max_holding_exit": int(stats.get("max_holding_exit", 0) or 0),
                "reentry_executed": int(stats.get("reentry_executed", 0) or 0),
                "premium_blocked": int(stats.get("premium_blocked", 0) or 0),
                "market_blocked": int(stats.get("market_blocked", 0) or 0),
                # 信号质量
                "avg_buy_score": signals_analyzed.get("avg_buy_score", "N/A"),
                "median_adx": signals_analyzed.get("median_adx", "N/A"),
                # 持有期分析
                "holding_win_pct": holding_win,
                "holding_loss_pct": holding_loss,
            }
            all_rows.append(row)

            # 打印结果
            _print_cluster_result(cid, name, row)

    dispose_engine()

    # 写入 CSV
    import pandas as pd
    df = pd.DataFrame(all_rows)
    out_path = os.path.join(OUT_DIR, "cluster_backtest_comparison.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n对比结果已保存: {out_path}")

    # 打印组间差异摘要
    print(f"\n{'='*80}")
    print("  分组间差异摘要")
    print(f"{'='*80}")
    for window_label in ["2016-2026", "2024-2026"]:
        window_rows = [r for r in all_rows if r["window"] == window_label]
        if not window_rows:
            continue
        print(f"\n  --- {window_label} ---")
        for r in window_rows:
            prefix = f"  [{r['cluster_name']:20s}]"
            print(f"{prefix} 年化={r['annual_return']:>8s}  回撤={r['max_drawdown']:>8s}  "
                  f"胜率={r['win_rate']:>8s}  交易={r['total_trades']:>4d}  "
                  f"止损={r['stop_loss_triggered']:>3d}")


def _print_cluster_result(cid, name, row):
    print(f"\n  [{name}] ({row['etf_count']}只ETF)")
    print(f"    年化: {row['annual_return']:>8s}  回撤: {row['max_drawdown']:>8s}  "
          f"Calmar: {row['calmar']:>8s}  Sharpe: {row['sharpe']:>8s}")
    print(f"    胜率: {row['win_rate']:>8s}  利润因子: {row['profit_factor']:>8s}  "
          f"交易: {row['total_trades']:>4d}")
    print(f"    止损: {row['stop_loss_triggered']:>3d}  持有到期: {row['max_holding_exit']:>3d}  "
          f"再入场: {row['reentry_executed']:>3d}")
    print(f"    均价BUY score: {row['avg_buy_score']:>8s}  "
          f"中位ADX: {row['median_adx']:>8s}")
    print(f"    持有盈利比例: {row['holding_win_pct']}  持有亏损比例: {row['holding_loss_pct']}")


def _analyze_signals(codes, start, end):
    """计算信号质量指标：BUY 时的平均 score、中位 ADX。"""
    from src.database.repository import signals_repo, indicators_repo
    scores = []
    adx_vals = []
    for code in codes:
        sigs = signals_repo.find_by_code_between(code, start, end)
        for s in sigs:
            if s.signal == "BUY" and s.signal_meta:
                sc = s.signal_meta.get("score")
                if sc is not None:
                    scores.append(float(sc))
                adx = s.signal_meta.get("adx")
                if adx is not None:
                    adx_vals.append(float(adx))
    return {
        "avg_buy_score": f"{np.mean(scores):.1f}" if scores else "N/A",
        "median_adx": f"{np.median(adx_vals):.1f}" if adx_vals else "N/A",
    }


def _holding_win_rate(trades):
    """计算持仓盈利/亏损比例。"""
    from src.backtest.portfolio_metrics import pair_closed_trades
    closed = pair_closed_trades(trades)
    if not closed:
        return "N/A", "N/A"
    wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
    losses = sum(1 for t in closed if t.get("pnl", 0) <= 0)
    total = wins + losses
    return f"{wins}/{total}={wins/total:.0%}" if total > 0 else "N/A", f"{losses}/{total}={losses/total:.0%}" if total > 0 else "N/A"


if __name__ == "__main__":
    main()
