"""Bottom-layer volatility profile strategy experiment report."""

from datetime import date, timedelta
from typing import Any

from src.backtest.ablation_config import (
    high_vol_profile_strategy_experiments,
    low_vol_profile_strategy_experiments,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.service.calendar_service import TradingCalendarService


def run_volatility_profile_strategy_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run high-vol and low-vol bottom-layer strategy experiments."""
    from src.config import load_config

    config = load_config()
    selected = set(codes or [e.symbol for e in config.etf_list])

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())
    if start is None:
        start = end - timedelta(days=config.lookback_days)

    high_items = [
        item for item in config.etf_list
        if item.symbol in selected and item.volatility_group == "high_vol"
    ]
    low_items = [
        item for item in config.etf_list
        if item.symbol in selected and item.volatility_group == "low_vol"
    ]

    groups = []
    if high_items:
        high_codes = [item.symbol for item in high_items]
        high_result = run_ablation_backtest(
            codes=high_codes,
            start=start,
            end=end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=high_vol_profile_strategy_experiments(),
            matrix="high-vol-profile-strategy",
        )
        high_result["meta"]["baseline_name"] = "baseline_v2_4_segment_stop"
        groups.append({
            "name": "高波动",
            "volatility_group": "high_vol",
            "codes": high_codes,
            "etfs": [_item_record(item) for item in high_items],
            "result": high_result,
        })

    if low_items:
        low_codes = [item.symbol for item in low_items]
        low_result = run_ablation_backtest(
            codes=low_codes,
            start=start,
            end=end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=low_vol_profile_strategy_experiments(),
            matrix="low-vol-profile-strategy",
        )
        low_result["meta"]["baseline_name"] = "baseline_v2_4_segment_stop"
        groups.append({
            "name": "低波动",
            "volatility_group": "low_vol",
            "codes": low_codes,
            "etfs": [_item_record(item) for item in low_items],
            "result": low_result,
        })

    return {
        "meta": {
            "start": str(start),
            "end": str(end),
            "codes": [item.symbol for item in config.etf_list if item.symbol in selected],
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "volatility-profile-strategy",
        },
        "groups": groups,
    }


def format_volatility_profile_strategy_report(result: dict[str, Any]) -> str:
    """Format high/low volatility profile strategy experiment results."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 132)
    lines.append("  高低波动 ETF 底层策略分离消融实验报告")
    lines.append("=" * 132)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  回测区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("")
    lines.append("  实验分组:")
    lines.append("  - 高波动: baseline-v2.4 vs 高波新底层信号 vs 高波新底层信号+高波趋势风控。")
    lines.append("  - 低波动: baseline-v2.4 vs 低波新底层信号 vs 低波新底层信号+低波结构风控。")
    lines.append("")

    for group in result.get("groups", []):
        _append_group(lines, group)

    lines.append("  说明:")
    lines.append("  - 新信号均为回测内存生成，不覆盖生产 signals。")
    lines.append("  - 新信号+baseline风控 用于隔离底层信号贡献；新信号+新风控 用于验证完整候选策略。")
    lines.append("  - Δ回撤为相对 baseline-v2.4 的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def _append_group(lines: list[str], group: dict[str, Any]) -> None:
    result = group["result"]
    versions = result.get("versions", {})
    baseline = versions.get("baseline_v2_4_segment_stop")
    if baseline is None:
        return
    baseline_summary = baseline["summary"]

    lines.append(f"  分组: {group['name']} ETF={len(group['codes'])}")
    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "Sharpe",
        "胜率", "Δ胜率", "PF", "交易", "止损", "90日", "移停", "趋退", "结退", "灾停",
    ]
    cols = [18, 9, 9, 9, 9, 8, 8, 9, 9, 8, 6, 6, 6, 6, 6, 6, 6]
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
            f" {str(stats.get('trailing_stop_exit', 0)):>6s}"
            f" {str(stats.get('trend_exit', 0)):>6s}"
            f" {str(stats.get('structure_exit', 0)):>6s}"
            f" {str(stats.get('disaster_stop', 0)):>6s}"
        )
    lines.append("")
    lines.append(f"  {group['name']} ETF: {', '.join(group['codes'])}")
    lines.append("")


def _item_record(item) -> dict[str, str]:
    return {
        "symbol": item.symbol,
        "name": item.name,
        "market": item.regime_group,
        "volatility_group": item.volatility_group,
    }


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
