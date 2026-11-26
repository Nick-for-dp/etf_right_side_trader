"""Volatility-group strategy experiment report."""

from datetime import date, timedelta
from typing import Any

from src.backtest.ablation_config import (
    volatility_strategy_no_risk_experiments,
    volatility_strategy_production_experiments,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.service.calendar_service import TradingCalendarService


def run_volatility_strategy_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run the two-layer volatility strategy experiment."""
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
        experiments=volatility_strategy_no_risk_experiments(),
        matrix="volatility-strategy-no-risk",
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
        experiments=volatility_strategy_production_experiments(),
        matrix="volatility-strategy-production",
    )
    production["meta"]["baseline_name"] = "baseline_v2_4_segment_stop"

    segments = []
    selected_codes = set(codes)
    for segment in _build_volatility_segments(config.etf_list, selected_codes):
        segment_result = production if segment["name"] == "全池" else run_ablation_backtest(
            codes=segment["codes"],
            start=start,
            end=end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=volatility_strategy_production_experiments(),
            matrix="volatility-strategy-segment",
        )
        segment_result["meta"]["baseline_name"] = "baseline_v2_4_segment_stop"
        segments.append({**segment, "result": segment_result})

    return {
        "meta": {
            "start": str(start),
            "end": str(end),
            "codes": codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "volatility-strategy",
        },
        "no_risk": no_risk,
        "production": production,
        "segments": segments,
    }


def format_volatility_strategy_report(result: dict[str, Any]) -> str:
    """Format the volatility strategy experiment report."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 124)
    lines.append("  高低波动 ETF 差异化策略实验报告")
    lines.append("=" * 124)
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
    if result.get("segments"):
        lines.append("")
        lines.append("  附：生产口径分波动组诊断")
        lines.append("  口径: 与第二层一致，只改变 ETF 分组样本；样本不足分组只作观察。")
        _append_segment_table(lines, result["segments"], "baseline_v2_4_segment_stop")
    lines.append("")
    lines.append("  说明:")
    lines.append("  - 高波严格: high_vol 建仓 score >= 60，加仓两阶阈值 70/75。")
    lines.append("  - 低波宽加: low_vol 保持原建仓信号，加仓两阶阈值 55/60。")
    lines.append("  - 第一层只验证高低波差异化执行规则的独立价值，第二层才用于生产采纳判断。")
    return "\n".join(lines)


def _build_volatility_segments(etf_items: list, selected_codes: set[str]) -> list[dict[str, Any]]:
    """Build fixed volatility-focused validation segments from config metadata."""
    items = [
        item for item in etf_items
        if item.symbol in selected_codes
    ]

    def item_record(item) -> dict[str, str]:
        return {
            "symbol": item.symbol,
            "name": item.name,
            "market": item.regime_group,
            "volatility_group": item.volatility_group,
        }

    specs = [
        ("全池", "全部 ETF", lambda item: True),
        ("高波动", "全部 high_vol", lambda item: item.volatility_group == "high_vol"),
        ("低波动", "全部 low_vol", lambda item: item.volatility_group == "low_vol"),
        ("A股高波动", "A股 high_vol", lambda item: item.regime_group == "A股" and item.volatility_group == "high_vol"),
        ("A股低波动", "A股 low_vol", lambda item: item.regime_group == "A股" and item.volatility_group == "low_vol"),
    ]

    segments = []
    for name, label, predicate in specs:
        segment_items = [item for item in items if predicate(item)]
        if not segment_items:
            continue
        segments.append({
            "name": name,
            "label": label,
            "codes": [item.symbol for item in segment_items],
            "etfs": [item_record(item) for item in segment_items],
            "sample_warning": len(segment_items) < 3,
        })
    return segments


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
        "胜率", "Δ胜率", "PF", "交易", "入场候选", "入场拦截", "加仓候选", "加仓拦截",
    ]
    cols = [14, 9, 9, 9, 9, 8, 8, 9, 9, 8, 6, 8, 8, 8, 8]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for name, item in versions.items():
        summary = item["summary"]
        stats = item.get("stats", {})
        exp = item.get("experiment", {})
        label = exp.get("label") or name
        lines.append(
            f"  {label[:14]:14s}"
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
            f" {str(stats.get('vol_entry_candidates', 0)):>8s}"
            f" {str(stats.get('vol_entry_blocked', 0)):>8s}"
            f" {str(stats.get('vol_add_candidates', 0)):>8s}"
            f" {str(stats.get('vol_add_blocked', 0)):>8s}"
        )


def _append_segment_table(
    lines: list[str],
    segments: list[dict[str, Any]],
    baseline_name: str,
) -> None:
    headers = [
        "分组", "ETF", "样本", "实验", "年化", "Δ年化", "回撤", "Δ回撤",
        "Calmar", "胜率", "PF", "交易", "入拦", "加拦",
    ]
    cols = [10, 4, 8, 14, 9, 9, 9, 9, 8, 9, 8, 6, 6, 6]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for segment in segments:
        versions = segment["result"].get("versions", {})
        baseline = versions.get(baseline_name)
        if baseline is None:
            continue
        baseline_summary = baseline["summary"]
        for _name, item in versions.items():
            summary = item["summary"]
            stats = item.get("stats", {})
            exp = item.get("experiment", {})
            label = exp.get("label") or _name
            lines.append(
                f"  {segment['name'][:10]:10s}"
                f" {len(segment['codes']):>4d}"
                f" {_sample_label(segment):>8s}"
                f" {label[:14]:14s}"
                f" {_metric(summary, 'annual_return'):>9s}"
                f" {_delta_pct(summary, baseline_summary, 'annual_return', lower_is_better=False):>9s}"
                f" {_metric(summary, 'max_drawdown'):>9s}"
                f" {_delta_pct(summary, baseline_summary, 'max_drawdown', lower_is_better=True):>9s}"
                f" {summary.get('calmar', 'N/A'):>8s}"
                f" {_metric(summary, 'win_rate'):>9s}"
                f" {summary.get('profit_factor', 'N/A'):>8s}"
                f" {summary.get('total_trades', 'N/A'):>6s}"
                f" {str(stats.get('vol_entry_blocked', 0)):>6s}"
                f" {str(stats.get('vol_add_blocked', 0)):>6s}"
            )
        lines.append("")

    lines.append("  分组 ETF:")
    for segment in segments:
        lines.append(f"  - {segment['name']}: {', '.join(segment['codes'])}")


def _sample_label(segment: dict[str, Any]) -> str:
    return "样本不足" if segment.get("sample_warning") else "可参考"


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
