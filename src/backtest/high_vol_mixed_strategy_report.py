"""Full-pool validation for the high-volatility experimental signal."""

from datetime import date, timedelta
from typing import Any

from src.backtest.ablation_config import high_vol_mixed_strategy_experiments
from src.backtest.ablation_report import run_ablation_backtest
from src.service.calendar_service import TradingCalendarService


def run_high_vol_mixed_strategy_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run full-pool high-vol mixed signal validation over long/recent windows."""
    from src.config import load_config

    config = load_config()
    selected_codes = codes or [e.symbol for e in config.etf_list]
    selected_set = set(selected_codes)

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]
    experiments = high_vol_mixed_strategy_experiments()
    results = []
    for label, start, window_end in windows:
        result = run_ablation_backtest(
            codes=selected_codes,
            start=start,
            end=window_end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=experiments,
            matrix="high-vol-mixed-strategy",
        )
        result["meta"]["window"] = label
        result["meta"]["baseline_name"] = "baseline_v2_4_segment_stop"
        results.append(result)

    high_codes = [
        item.symbol for item in config.etf_list
        if item.symbol in selected_set and item.volatility_group == "high_vol"
    ]
    low_codes = [
        item.symbol for item in config.etf_list
        if item.symbol in selected_set and item.volatility_group == "low_vol"
    ]
    return {
        "meta": {
            "codes": selected_codes,
            "high_vol_codes": high_codes,
            "low_vol_codes": low_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "high-vol-mixed-strategy",
        },
        "windows": results,
    }


def format_high_vol_mixed_strategy_report(result: dict[str, Any]) -> str:
    """Format full-pool high-vol mixed validation results."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 122)
    lines.append("  高波新信号全池混合验证报告")
    lines.append("=" * 122)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  候选: high_vol 使用高波新底层信号；low_vol 保持 baseline-v2.4。")
    lines.append("  风控: baseline-v2.4 的 70/15/15、分 profile 止损、90 日最大持有、gate-lite 全部保持不变。")
    lines.append("")

    for window in result.get("windows", []):
        _append_window(lines, window)

    lines.append("  分组 ETF:")
    lines.append(f"  - high_vol: {', '.join(meta['high_vol_codes'])}")
    lines.append(f"  - low_vol: {', '.join(meta['low_vol_codes'])}")
    lines.append("")
    lines.append("  说明:")
    lines.append("  - 本实验只验证全池组合效果，不覆盖生产 signals。")
    lines.append("  - Δ回撤为相对 baseline-v2.4 的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def _append_window(lines: list[str], result: dict[str, Any]) -> None:
    meta = result["meta"]
    versions = result.get("versions", {})
    baseline = versions.get("baseline_v2_4_segment_stop")
    if baseline is None:
        return
    baseline_summary = baseline["summary"]
    lines.append(f"  区间: {meta['window']} ({meta['start']} ~ {meta['end']})")
    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "Sharpe",
        "胜率", "Δ胜率", "PF", "交易", "止损", "90日", "加仓",
    ]
    cols = [18, 9, 9, 9, 9, 8, 8, 9, 9, 8, 6, 6, 6, 6]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for _name, item in versions.items():
        summary = item["summary"]
        stats = item.get("stats", {})
        exp = item.get("experiment", {})
        label = exp.get("label") or _name
        lines.append(
            f"  {label[:18]:18s}"
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
            f" {str(stats.get('stop_loss_triggered', 0)):>6s}"
            f" {str(stats.get('max_holding_exit', 0)):>6s}"
            f" {str(stats.get('add_executed', 0)):>6s}"
        )
    lines.append("")


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
