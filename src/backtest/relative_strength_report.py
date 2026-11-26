"""Relative-strength two-layer backtest report."""

from datetime import date, timedelta
from typing import Any

from src.backtest.ablation_config import (
    relative_strength_no_risk_experiments,
    relative_strength_production_experiments,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.service.calendar_service import TradingCalendarService


def run_relative_strength_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run the two-layer RS experiment.

    Layer 1 isolates RS selection value by disabling stop-loss and max-holding
    exits while keeping baseline-v2.4 signals, gates, 70/15/15 and position
    constraints. Layer 2 compares all RS candidates against full baseline-v2.4.
    """
    from src.config import load_config

    config = load_config()
    if codes is None:
        codes = [e.symbol for e in config.etf_list]

    calendar = TradingCalendarService()
    if end is None:
        end_str = calendar.get_previous_trading_day()
        end = date.fromisoformat(end_str)
    if start is None:
        start = end - timedelta(days=config.lookback_days)

    no_risk = run_ablation_backtest(
        codes=codes,
        start=start,
        end=end,
        capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        experiments=relative_strength_no_risk_experiments(),
        matrix="relative-strength-no-risk",
    )
    no_risk["meta"]["baseline_name"] = "control_no_risk"

    production = run_ablation_backtest(
        codes=codes,
        start=start,
        end=end,
        capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        experiments=relative_strength_production_experiments(),
        matrix="relative-strength-production",
    )
    production["meta"]["baseline_name"] = "baseline_v2_4_segment_stop"

    return {
        "meta": {
            "start": str(start),
            "end": str(end),
            "codes": codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "relative-strength",
        },
        "no_risk": no_risk,
        "production": production,
    }


def format_relative_strength_report(result: dict[str, Any]) -> str:
    """Format the two-layer RS experiment report."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 118)
    lines.append("  横截面相对强弱两层实验报告")
    lines.append("=" * 118)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  回测区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("")
    lines.append("  第一层：信号效果隔离实验")
    lines.append("  口径: baseline-v2.4 信号、gate-lite、70/15/15 和仓位约束；关闭 stop-loss 和 90 日最大持有。")
    _append_layer_table(lines, result["no_risk"], "control_no_risk")
    lines.append("")
    lines.append("  第二层：生产口径对比实验")
    lines.append("  口径: 与 baseline-v2.4 完全一致的资金、成本、滑点、仓位、gate-lite、70/15/15、分 profile 止损和 90 日最大持有。")
    _append_layer_table(lines, result["production"], "baseline_v2_4_segment_stop")
    lines.append("")
    lines.append("  说明:")
    lines.append("  - 第一层只用于筛选 RS 因子价值，不能宣称优于 baseline-v2.4。")
    lines.append("  - 第二层才用于生产采纳判断。")
    lines.append("  - RS收益排序按 20/60/120 日收益综合分排序；RS超额排序按相对所属市场基准超额收益排序。")
    lines.append("  - RS前40% 只允许综合强弱排名前 40% 的 BUY 进入建仓/加仓。")
    return "\n".join(lines)


def _append_layer_table(
    lines: list[str],
    layer_result: dict[str, Any],
    baseline_name: str,
) -> None:
    versions = layer_result.get("versions", {})
    if not versions:
        lines.append("  无可用结果：请确认 signals 和行情数据已完成重算。")
        return
    baseline = versions.get(baseline_name) or next(iter(versions.values()))
    baseline_summary = baseline["summary"]

    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "Sharpe",
        "胜率", "Δ胜率", "PF", "交易", "RS候选", "RS通过", "RS拦截",
    ]
    cols = [16, 9, 9, 9, 9, 8, 8, 9, 9, 8, 6, 8, 8, 8]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for name, item in versions.items():
        summary = item["summary"]
        stats = item.get("stats", {})
        exp = item.get("experiment", {})
        label = exp.get("label") or name
        lines.append(
            f"  {label[:16]:16s}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'annual_return', lower_is_better=False):>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'max_drawdown', lower_is_better=True):>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {summary.get('sharpe', 'N/A'):>8s}"
            f" {_metric(summary, 'win_rate'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'win_rate', lower_is_better=False):>9s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {str(stats.get('rs_buy_candidates', 0)):>8s}"
            f" {str(stats.get('rs_buy_allowed', 0)):>8s}"
            f" {str(stats.get('rs_buy_blocked', 0)):>8s}"
        )


def _metric(summary: dict[str, Any], key: str) -> str:
    return str(summary.get(key, "N/A"))


def _delta_pct(
    summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    key: str,
    *,
    lower_is_better: bool,
) -> str:
    current = _parse_percent(summary.get(key))
    baseline = _parse_percent(baseline_summary.get(key))
    if current is None or baseline is None:
        return "N/A"
    delta = baseline - current if lower_is_better else current - baseline
    return f"{delta * 100:+.2f}%"


def _parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "N/A":
        return None
    if text.endswith("%"):
        text = text[:-1]
        try:
            return float(text) / 100
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None
