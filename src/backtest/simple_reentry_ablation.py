#!/usr/bin/env python
"""简单止损后再入场消融实验 — 4个思路对照。

思路1 (baseline): 无过滤，止损后等自然BUY重新入场
思路2 (3T冷却):  止损后等3个交易日才允许重新入场
思路3 (止损价约束): 重新入场价必须高于止损卖出价
思路4 (跳过首BUY): 止损后跳过第一个BUY信号，等第二个新BUY

用法:
    uv run python src/backtest/simple_reentry_ablation.py

输出:
    src/backtest/simple_reentry_report.md
"""

import sys
import os
from datetime import date

_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.backtest.ablation_config import (
    AblationExperimentConfig,
    REENTRY_COOLDOWN_3T,
    REENTRY_PRICE_ABOVE_STOP,
    REENTRY_SKIP_FIRST_BUY,
    BUDGET_RULE_70_15_15_LADDER,
    MONTHLY_QUARTER_90D,
    STOP_LOSS_FIXED_8,
)
from src.backtest.portfolio_backtest import PortfolioBacktest
from src.config import load_config
from src.database import init_engine, dispose_engine
from src.service.calendar_service import TradingCalendarService


def main():
    config = load_config()
    engine = init_engine(config.db_url)

    calendar = TradingCalendarService()
    end = date.fromisoformat(calendar.get_previous_trading_day())
    codes = [e.symbol for e in config.etf_list]
    code_regime_groups = {e.symbol: e.regime_group for e in config.etf_list}
    code_stop_loss_profiles = {e.symbol: e.stop_loss_profile for e in config.etf_list}
    code_volatility_groups = {
        e.symbol: getattr(e, "volatility_group", "unknown_vol")
        for e in config.etf_list
    }

    windows = [
        ("2016-2026全量", date(2016, 1, 1), end),
        ("2024-2026近期", date(2024, 1, 1), end),
    ]

    base_config = dict(
        max_holding_days=90,
        cycle_profile=MONTHLY_QUARTER_90D,
        entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
        stop_loss_rule=STOP_LOSS_FIXED_8,
        use_config_stop_loss_profiles=True,
    )
    experiments = [
        AblationExperimentConfig(
            name="baseline_no_reentry",
            label="baseline(无过滤)",
            reentry_rule=None,
            description="对照组(v2.4基线)：无止损后再入场过滤",
            **base_config,
        ),
        AblationExperimentConfig(
            name="simple_cooldown_3t",
            label="3T冷却",
            reentry_rule=REENTRY_COOLDOWN_3T,
            description="v2.4基线 + 止损后等3个交易日才允许重新入场",
            **base_config,
        ),
        AblationExperimentConfig(
            name="simple_price_above_stop",
            label="止损价约束",
            reentry_rule=REENTRY_PRICE_ABOVE_STOP,
            description="v2.4基线 + 重新入场价必须高于止损卖出价",
            **base_config,
        ),
        AblationExperimentConfig(
            name="simple_skip_first_buy",
            label="跳过首BUY",
            reentry_rule=REENTRY_SKIP_FIRST_BUY,
            description="v2.4基线 + 止损后跳过第一个BUY信号",
            **base_config,
        ),
    ]

    all_results = []
    for label, start, w_end in windows:
        print(f"\n  === 窗口: {label} ({start} ~ {w_end}) ===")
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
            codes=codes, start=start, end=w_end, experiments=experiments,
        )
        result["meta"]["window"] = label
        all_results.append(result)

        # stdout
        _print_results(result, experiments)

    # markdown
    md = _build_report(all_results, experiments, codes, end)
    report_path = os.path.join(os.path.dirname(__file__), "simple_reentry_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n  报告: {report_path}")

    dispose_engine()


def _print_results(result, experiments):
    versions = result.get("versions", {})
    baseline = versions.get("baseline_no_reentry", {})
    bs = baseline.get("summary", {})

    headers = ["实验", "年化", "Δ年化", "回撤", "Δ回撤", "胜率", "Δ胜率", "PF",
               "交易", "止损", "再入场", "拦截", "执行", "再入场盈亏", "采纳判断"]
    cols = [18, 9, 9, 9, 9, 8, 8, 7, 6, 6, 8, 6, 6, 10, 10]
    print("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    print("  " + "  ".join("-" * c for c in cols))

    for exp in experiments:
        item = versions.get(exp.name, {})
        s = item.get("summary", {})
        st = item.get("stats", {})
        label = exp.label

        ar = _d(s, "annual_return")
        dd = _d(s, "max_drawdown")
        wr = _d(s, "win_rate")

        ba_ar = _d(bs, "annual_return")
        ba_dd = _d(bs, "max_drawdown")
        ba_wr = _d(bs, "win_rate")

        ar_d = _delta(ar, ba_ar, lower=False)
        dd_d = _delta(ba_dd, dd, lower=True)
        wr_d = _delta_abs(wr, ba_wr)

        j = _judge(ar, ba_ar, dd, ba_dd, wr, ba_wr)

        reentry = st.get("reentry_executed", 0)
        blocked = st.get("reentry_blocked", 0)
        attempts = st.get("reentry_attempts", 0)
        pnl = st.get("reentry_pnl_total", 0.0)

        print(
            f"  {label[:18]:18s}"
            f" {ar:>9s}"
            f" {ar_d:>9s}"
            f" {dd:>9s}"
            f" {dd_d:>9s}"
            f" {wr:>8s}"
            f" {wr_d:>8s}"
            f" {_d(s, 'profit_factor'):>7s}"
            f" {_d(s, 'total_trades'):>6s}"
            f" {str(st.get('stop_loss_triggered', 0)):>6s}"
            f" {str(attempts):>8s}"
            f" {str(blocked):>6s}"
            f" {str(reentry):>6s}"
            f" {f'{pnl:+,.0f}':>10s}"
            f" {j:>10s}"
        )
    print()


def _build_report(all_results, experiments, codes, end):
    lines = []
    lines.append("# 简单止损后再入场消融实验报告")
    lines.append("")
    lines.append(f"> 生成日期: {date.today().isoformat()}")
    lines.append(f"> 回测截止: {end}")
    lines.append(f"> ETF 数量: {len(codes)}")
    lines.append("")

    lines.append("## 实验设计")
    lines.append("")
    lines.append("| 思路 | 规则 | 说明 |")
    lines.append("|---|---|---|")
    lines.append("| 1 (对照组) | 无过滤 | 止损后等自然BUY信号重新建仓，等同首次建仓 |")
    lines.append("| 2 | 3T冷却 | 止损后等待3个交易日才允许重新入场 |")
    lines.append("| 3 | 止损价约束 | 重新入场价必须高于止损卖出价，避免\"贱卖后马上贵买\" |")
    lines.append("| 4 | 跳过首BUY | 止损后跳过第一个BUY信号，等第二个新BUY才入场 |")
    lines.append("")

    lines.append("## 控制变量说明")
    lines.append("")
    lines.append("- 所有实验组在基线(v2.4: 70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有)之上")
    lines.append("  只增加对应的再入场过滤逻辑，其余参数完全一致")
    lines.append("- 思路2/3/4互相独立，各自仅在思路1的基础上加一条规则")
    lines.append("")

    for result in all_results:
        window = result["meta"].get("window", "")
        lines.append(f"---")
        lines.append("")
        lines.append(f"## 窗口: {window}")
        lines.append("")
        lines.append("```")
        _append_table_lines(lines, result, experiments)
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 结论与建议")
    lines.append("")
    lines.append("> 由 `src/backtest/simple_reentry_ablation.py` 自动生成。")
    return "\n".join(lines)


def _append_table_lines(lines, result, experiments):
    versions = result.get("versions", {})
    baseline = versions.get("baseline_no_reentry", {})
    bs = baseline.get("summary", {})

    headers = ["实验", "年化", "Δ年化", "回撤", "Δ回撤", "胜率", "Δ胜率",
               "PF", "交易", "止损", "再入场", "拦截", "执行", "再入场盈亏", "采纳判断"]
    cols = [18, 9, 9, 9, 9, 8, 8, 7, 6, 6, 8, 6, 6, 10, 10]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))

    for exp in experiments:
        item = versions.get(exp.name, {})
        s = item.get("summary", {})
        st = item.get("stats", {})
        label = exp.label

        ar = _d(s, "annual_return")
        dd = _d(s, "max_drawdown")
        wr = _d(s, "win_rate")

        ba_ar = _d(bs, "annual_return")
        ba_dd = _d(bs, "max_drawdown")
        ba_wr = _d(bs, "win_rate")

        ar_d = _delta(ar, ba_ar, lower=False)
        dd_d = _delta(ba_dd, dd, lower=True)
        wr_d = _delta_abs(wr, ba_wr)

        j = _judge(ar, ba_ar, dd, ba_dd, wr, ba_wr)

        reentry = st.get("reentry_executed", 0)
        blocked = st.get("reentry_blocked", 0)
        attempts = st.get("reentry_attempts", 0)
        pnl = st.get("reentry_pnl_total", 0.0)

        lines.append(
            f"  {label[:18]:18s}"
            f" {ar:>9s}"
            f" {ar_d:>9s}"
            f" {dd:>9s}"
            f" {dd_d:>9s}"
            f" {wr:>8s}"
            f" {wr_d:>8s}"
            f" {_d(s, 'profit_factor'):>7s}"
            f" {_d(s, 'total_trades'):>6s}"
            f" {str(st.get('stop_loss_triggered', 0)):>6s}"
            f" {str(attempts):>8s}"
            f" {str(blocked):>6s}"
            f" {str(reentry):>6s}"
            f" {f'{pnl:+,.0f}':>10s}"
            f" {j:>10s}"
        )


def _d(summary, key):
    v = summary.get(key)
    if v is None:
        return "N/A"
    return str(v)


def _parse(v):
    if v is None or v == "N/A":
        return None
    t = str(v).strip().rstrip("%")
    try:
        return float(t) / 100 if "%" in str(v) else float(t)
    except ValueError:
        return None


def _delta(v_str, b_str, lower=False):
    v = _parse(v_str)
    b = _parse(b_str)
    if v is None or b is None:
        return "N/A"
    d = (b - v) if lower else (v - b)
    return f"{d * 100:+.2f}%"


def _delta_abs(v_str, b_str):
    v = _parse(v_str)
    b = _parse(b_str)
    if v is None or b is None:
        return "N/A"
    return f"{(v - b) * 100:+.2f}%"


def _judge(ar_s, ba_ar_s, dd_s, ba_dd_s, wr_s, ba_wr_s):
    ar = _parse(ar_s)
    ba_ar = _parse(ba_ar_s)
    dd = _parse(dd_s)
    ba_dd = _parse(ba_dd_s)
    wr = _parse(wr_s)
    ba_wr = _parse(ba_wr_s)

    parts = []
    if ar is not None and ba_ar is not None and ba_ar != 0:
        if (ar - ba_ar) / abs(ba_ar) >= 0.05:
            parts.append("年化+5%")
    if dd is not None and ba_dd is not None and ba_dd != 0:
        if (ba_dd - dd) / abs(ba_dd) >= 0.05:
            parts.append("回撤-5%")
    if wr is not None and ba_wr is not None:
        if (wr - ba_wr) >= 0.03:
            parts.append("胜率+3pct")
    if not parts:
        parts.append("—")
    return "|".join(parts)


if __name__ == "__main__":
    main()
