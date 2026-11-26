"""Robustness checks for high-volatility quality-tier position sizing."""

from datetime import date
from typing import Any

from src.backtest.ablation_config import (
    high_vol_quality_tier_candidate_experiments,
    high_vol_quality_tier_sensitivity_experiments,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.service.calendar_service import TradingCalendarService

BASELINE_NAME = "baseline_v2_4_segment_stop"
MIXED_NAME = "mixed_high_vol_signal"
TIER_NAME = "high_vol_quality_budget_tier"


def run_high_vol_quality_tier_robustness_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run sensitivity, rolling-window and attribution checks for quality tiering."""
    from src.config import load_config

    config = load_config()
    selected_codes = codes or [e.symbol for e in config.etf_list]
    selected_set = set(selected_codes)

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    sensitivity_windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]
    rolling_windows = [
        ("2016-2019", date(2016, 1, 1), min(date(2019, 12, 31), end)),
        ("2020-2022", date(2020, 1, 1), min(date(2022, 12, 31), end)),
        ("2023-2026", date(2023, 1, 1), end),
    ]
    rolling_windows = [item for item in rolling_windows if item[1] <= item[2]]

    sensitivity_experiments = high_vol_quality_tier_sensitivity_experiments()
    candidate_experiments = high_vol_quality_tier_candidate_experiments()

    sensitivity_results = []
    for label, start, window_end in sensitivity_windows:
        result = _run_matrix(
            selected_codes,
            start,
            window_end,
            capital,
            cost_ratio,
            slippage,
            position_limit,
            sensitivity_experiments,
            "high-vol-quality-tier-sensitivity",
        )
        result["meta"]["window"] = label
        sensitivity_results.append(result)

    rolling_results = []
    for label, start, window_end in rolling_windows:
        result = _run_matrix(
            selected_codes,
            start,
            window_end,
            capital,
            cost_ratio,
            slippage,
            position_limit,
            candidate_experiments,
            "high-vol-quality-tier-rolling",
        )
        result["meta"]["window"] = label
        rolling_results.append(result)

    high_vol_segments = _build_high_vol_segments(config.etf_list, selected_set)
    segment_results = []
    for segment in high_vol_segments:
        result = _run_matrix(
            segment["codes"],
            date(2016, 1, 1),
            end,
            capital,
            cost_ratio,
            slippage,
            position_limit,
            candidate_experiments,
            "high-vol-quality-tier-segment",
        )
        segment_results.append({**segment, "result": result})

    etf_results = []
    for item in _build_high_vol_etfs(config.etf_list, selected_set):
        result = _run_matrix(
            [item["symbol"]],
            date(2016, 1, 1),
            end,
            capital,
            cost_ratio,
            slippage,
            position_limit,
            candidate_experiments,
            "high-vol-quality-tier-etf",
        )
        etf_results.append({**item, "result": result, "judgement": _tier_judgement(result)})

    high_codes = [item["symbol"] for item in _build_high_vol_etfs(config.etf_list, selected_set)]
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
            "matrix": "high-vol-quality-tier-robustness",
            "baseline_name": BASELINE_NAME,
            "mixed_name": MIXED_NAME,
            "tier_name": TIER_NAME,
        },
        "sensitivity_windows": sensitivity_results,
        "rolling_windows": rolling_results,
        "segments": segment_results,
        "etfs": etf_results,
    }


def format_high_vol_quality_tier_robustness_report(result: dict[str, Any]) -> str:
    """Format quality-tier robustness checks."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 150)
    lines.append("  高波质量分层仓位稳健性验证报告")
    lines.append("=" * 150)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  候选: high_vol 使用高波新信号，并按 score 分层调整目标仓位；low_vol 保持 baseline-v2.4。")
    lines.append("  当前候选参数: score>=65 满额，55<=score<65 为 80%，score<55 为 60%。")
    lines.append("")

    lines.append("  一、参数敏感性")
    for window in result.get("sensitivity_windows", []):
        _append_sensitivity_window(lines, window)

    lines.append("  二、滚动窗口")
    _append_rolling(lines, result.get("rolling_windows", []))

    lines.append("  三、分市场归因")
    _append_segments(lines, result.get("segments", []))

    lines.append("  四、单 ETF 归因")
    _append_etfs(lines, result.get("etfs", []))

    lines.append("  说明:")
    lines.append("  - Δ年化/Δ回撤相对 baseline-v2.4；相对混合用于判断质量分层是否优于高波新信号混合候选。")
    lines.append("  - 分市场和单 ETF 归因只覆盖 high_vol ETF，用于定位分层仓位的收益来源和拖累来源。")
    return "\n".join(lines)


def _run_matrix(
    codes: list[str],
    start: date,
    end: date,
    capital: float,
    cost_ratio: float,
    slippage: float,
    position_limit: float,
    experiments,
    matrix: str,
) -> dict[str, Any]:
    result = run_ablation_backtest(
        codes=codes,
        start=start,
        end=end,
        capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        experiments=experiments,
        matrix=matrix,
    )
    result["meta"]["baseline_name"] = BASELINE_NAME
    result["meta"]["mixed_name"] = MIXED_NAME
    result["meta"]["tier_name"] = TIER_NAME
    return result


def _build_high_vol_segments(etf_items: list, selected_set: set[str]) -> list[dict[str, Any]]:
    high_items = [
        item for item in etf_items
        if item.symbol in selected_set and item.volatility_group == "high_vol"
    ]
    segments = []
    if high_items:
        segments.append({
            "name": "全部高波",
            "label": "all high_vol",
            "codes": [item.symbol for item in high_items],
            "sample_warning": len(high_items) < 3,
        })
    for market in ("A股", "港股", "美股"):
        items = [item for item in high_items if item.regime_group == market]
        if not items:
            continue
        segments.append({
            "name": f"{market}高波",
            "label": f"{market} high_vol",
            "codes": [item.symbol for item in items],
            "sample_warning": len(items) < 3,
        })
    return segments


def _build_high_vol_etfs(etf_items: list, selected_set: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": item.symbol,
            "name": item.name,
            "market": item.regime_group,
            "category": item.category,
        }
        for item in etf_items
        if item.symbol in selected_set and item.volatility_group == "high_vol"
    ]


def _append_sensitivity_window(lines: list[str], result: dict[str, Any]) -> None:
    meta = result["meta"]
    versions = result.get("versions", {})
    baseline = versions.get(BASELINE_NAME)
    mixed = versions.get(MIXED_NAME)
    if baseline is None or mixed is None:
        return
    baseline_summary = baseline["summary"]
    mixed_summary = mixed["summary"]
    lines.append(f"  区间: {meta['window']} ({meta['start']} ~ {meta['end']})")
    headers = ["实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "较混Cal", "PF", "交易", "仓位降", "判断"]
    cols = [16, 9, 9, 9, 9, 8, 8, 8, 6, 7, 8]
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
            f" {_delta_number(summary, mixed_summary, 'calmar'):>8s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {str(stats.get('quality_budget_scaled', 0)):>7s}"
            f" {_version_judgement(summary, baseline_summary, mixed_summary):>8s}"
        )
    lines.append("")


def _append_rolling(lines: list[str], windows: list[dict[str, Any]]) -> None:
    headers = ["区间", "baseline年化", "混合年化", "分层年化", "分层回撤", "分层Cal", "较混Cal", "判断"]
    cols = [12, 11, 10, 10, 10, 8, 8, 8]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for result in windows:
        meta = result["meta"]
        versions = result.get("versions", {})
        baseline = versions.get(BASELINE_NAME, {}).get("summary", {})
        mixed = versions.get(MIXED_NAME, {}).get("summary", {})
        tier = versions.get(TIER_NAME, {}).get("summary", {})
        lines.append(
            f"  {meta['window'][:12]:12s}"
            f" {_metric(baseline, 'annual_return'):>11s}"
            f" {_metric(mixed, 'annual_return'):>10s}"
            f" {_metric(tier, 'annual_return'):>10s}"
            f" {_metric(tier, 'max_drawdown'):>10s}"
            f" {tier.get('calmar', 'N/A'):>8s}"
            f" {_delta_number(tier, mixed, 'calmar'):>8s}"
            f" {_version_judgement(tier, baseline, mixed):>8s}"
        )
    lines.append("")


def _append_segments(lines: list[str], segments: list[dict[str, Any]]) -> None:
    headers = ["分组", "ETF", "混合年化", "分层年化", "分层回撤", "分层Cal", "较混Cal", "判断"]
    cols = [12, 4, 10, 10, 10, 8, 8, 8]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for segment in segments:
        versions = segment["result"].get("versions", {})
        baseline = versions.get(BASELINE_NAME, {}).get("summary", {})
        mixed = versions.get(MIXED_NAME, {}).get("summary", {})
        tier = versions.get(TIER_NAME, {}).get("summary", {})
        judgement = "观察" if segment.get("sample_warning") else _version_judgement(tier, baseline, mixed)
        lines.append(
            f"  {segment['name'][:12]:12s}"
            f" {len(segment['codes']):>4d}"
            f" {_metric(mixed, 'annual_return'):>10s}"
            f" {_metric(tier, 'annual_return'):>10s}"
            f" {_metric(tier, 'max_drawdown'):>10s}"
            f" {tier.get('calmar', 'N/A'):>8s}"
            f" {_delta_number(tier, mixed, 'calmar'):>8s}"
            f" {judgement:>8s}"
        )
    lines.append("")


def _append_etfs(lines: list[str], etfs: list[dict[str, Any]]) -> None:
    rows = []
    for item in etfs:
        versions = item["result"].get("versions", {})
        mixed = versions.get(MIXED_NAME, {}).get("summary", {})
        tier = versions.get(TIER_NAME, {}).get("summary", {})
        rows.append((
            _parse_number(_delta_number(tier, mixed, "calmar")) or -999.0,
            item,
            mixed,
            tier,
        ))
    rows.sort(key=lambda row: row[0], reverse=True)
    headers = ["代码", "市场", "混合年化", "分层年化", "分层回撤", "分层Cal", "较混Cal", "判断"]
    cols = [8, 6, 10, 10, 10, 8, 8, 8]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for _key, item, mixed, tier in rows:
        lines.append(
            f"  {item['symbol'][:8]:8s}"
            f" {item['market'][:6]:6s}"
            f" {_metric(mixed, 'annual_return'):>10s}"
            f" {_metric(tier, 'annual_return'):>10s}"
            f" {_metric(tier, 'max_drawdown'):>10s}"
            f" {tier.get('calmar', 'N/A'):>8s}"
            f" {_delta_number(tier, mixed, 'calmar'):>8s}"
            f" {item.get('judgement', '待判断'):>8s}"
        )
    lines.append("")


def _tier_judgement(result: dict[str, Any]) -> str:
    versions = result.get("versions", {})
    baseline = versions.get(BASELINE_NAME, {}).get("summary", {})
    mixed = versions.get(MIXED_NAME, {}).get("summary", {})
    tier = versions.get(TIER_NAME, {}).get("summary", {})
    return _version_judgement(tier, baseline, mixed)


def _version_judgement(
    summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    mixed_summary: dict[str, Any],
) -> str:
    annual = _parse_percent(summary.get("annual_return"))
    baseline_annual = _parse_percent(baseline_summary.get("annual_return"))
    drawdown = _parse_percent(summary.get("max_drawdown"))
    baseline_drawdown = _parse_percent(baseline_summary.get("max_drawdown"))
    calmar = _parse_number(summary.get("calmar"))
    mixed_calmar = _parse_number(mixed_summary.get("calmar"))
    if None in (annual, baseline_annual, drawdown, baseline_drawdown, calmar, mixed_calmar):
        return "待判断"
    annual_delta = annual - baseline_annual
    drawdown_improve = baseline_drawdown - drawdown
    if annual_delta >= 0.03 and drawdown_improve >= 0 and calmar >= mixed_calmar:
        return "稳健"
    if annual_delta >= 0.02 and calmar >= mixed_calmar:
        return "观察"
    if calmar < mixed_calmar or annual_delta < 0:
        return "拖累"
    return "中性"


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


def _delta_number(summary: dict[str, Any], baseline_summary: dict[str, Any], key: str) -> str:
    current = _parse_number(summary.get(key))
    baseline = _parse_number(baseline_summary.get(key))
    if current is None or baseline is None:
        return "N/A"
    return f"{current - baseline:+.4f}"


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
