"""High-volatility frequency-control experiment report."""

from datetime import date
from typing import Any

from src.backtest.ablation_config import (
    high_vol_frequency_combo_experiments,
    high_vol_frequency_single_experiments,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.service.calendar_service import TradingCalendarService


def run_high_vol_frequency_control_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run high-vol frequency controls over long/recent windows."""
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
    layers = [
        ("single", "单因素", high_vol_frequency_single_experiments()),
        ("combo", "组合候选", high_vol_frequency_combo_experiments()),
    ]

    layer_results = []
    for layer_key, layer_label, experiments in layers:
        window_results = []
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
                matrix=f"high-vol-frequency-{layer_key}",
            )
            result["meta"]["window"] = label
            result["meta"]["baseline_name"] = "baseline_v2_4_segment_stop"
            result["meta"]["mixed_name"] = "mixed_high_vol_signal"
            window_results.append(result)
        layer_results.append({
            "key": layer_key,
            "label": layer_label,
            "windows": window_results,
        })

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
            "matrix": "high-vol-frequency-control",
        },
        "layers": layer_results,
    }


def format_high_vol_frequency_control_report(result: dict[str, Any]) -> str:
    """Format high-vol frequency-control experiment results."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 150)
    lines.append("  高波新信号交易频率控制实验报告")
    lines.append("=" * 150)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  基础候选: high_vol 使用高波新底层信号；low_vol 保持 baseline-v2.4。")
    lines.append("  频控候选: 全部 high_vol 止损阈值固定为 -12%，再叠加 BUY/SELL/加仓/持仓数过滤。")
    lines.append("")

    for layer in result.get("layers", []):
        lines.append(f"  实验层: {layer['label']}")
        for window in layer.get("windows", []):
            _append_window(lines, window)
        lines.append("")

    lines.append("  分组 ETF:")
    lines.append(f"  - high_vol: {', '.join(meta['high_vol_codes'])}")
    lines.append(f"  - low_vol: {', '.join(meta['low_vol_codes'])}")
    lines.append("")
    lines.append("  说明:")
    lines.append("  - Δ年化/Δ回撤相对 baseline-v2.4；降交易相对高波新信号混合，正数表示交易减少。")
    lines.append("  - BUY拦/SELL拦/持有拦/加仓拦/持仓拦仅统计 high_vol 频控规则造成的过滤。")
    return "\n".join(lines)


def _append_window(lines: list[str], result: dict[str, Any]) -> None:
    meta = result["meta"]
    versions = result.get("versions", {})
    baseline = versions.get(meta.get("baseline_name", "baseline_v2_4_segment_stop"))
    mixed = versions.get(meta.get("mixed_name", "mixed_high_vol_signal"))
    if baseline is None or mixed is None:
        return
    baseline_summary = baseline["summary"]
    mixed_trades = _parse_number(mixed["summary"].get("total_trades"))

    lines.append(f"  区间: {meta['window']} ({meta['start']} ~ {meta['end']})")
    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "Sharpe",
        "胜率", "PF", "交易", "降交易", "止损", "BUY拦", "SELL拦",
        "持有拦", "加仓拦", "持仓拦",
    ]
    cols = [16, 9, 9, 9, 9, 8, 8, 9, 8, 6, 8, 6, 7, 7, 7, 7, 7]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for _name, item in versions.items():
        summary = item["summary"]
        stats = item.get("stats", {})
        exp = item.get("experiment", {})
        label = exp.get("label") or _name
        trades = _parse_number(summary.get("total_trades"))
        trade_reduction = (
            f"{int(mixed_trades - trades):+d}"
            if mixed_trades is not None and trades is not None
            else "N/A"
        )
        lines.append(
            f"  {label[:16]:16s}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'annual_return', lower_is_better=False):>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'max_drawdown', lower_is_better=True):>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {summary.get('sharpe', 'N/A'):>8s}"
            f" {_metric(summary, 'win_rate'):>9s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {trade_reduction:>8s}"
            f" {str(stats.get('stop_loss_triggered', 0)):>6s}"
            f" {str(stats.get('freq_buy_blocked', 0)):>7s}"
            f" {str(stats.get('freq_sell_blocked', 0)):>7s}"
            f" {str(stats.get('freq_min_hold_blocked', 0)):>7s}"
            f" {str(stats.get('freq_add_interval_blocked', 0)):>7s}"
            f" {str(stats.get('freq_max_positions_blocked', 0)):>7s}"
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


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None
