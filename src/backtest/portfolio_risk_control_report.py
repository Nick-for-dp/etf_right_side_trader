"""Portfolio-level risk control experiment report."""

from datetime import date
from typing import Any

from src.backtest.ablation_config import portfolio_risk_control_experiments
from src.backtest.ablation_report import run_ablation_backtest
from src.backtest.high_vol_quality_capital_attribution_report import (
    _attribute_version,
    _load_price_map,
)
from src.service.calendar_service import TradingCalendarService

BASELINE_NAME = "baseline_v2_4_segment_stop"
ANCHOR_NAME = "high_vol_quality_budget_tier"


def run_portfolio_risk_control_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run portfolio-level risk controls against the quality-tier anchor."""
    from src.config import load_config

    config = load_config()
    selected_codes = codes or [item.symbol for item in config.etf_list]
    selected_set = set(selected_codes)
    code_meta = {
        item.symbol: {
            "volatility_group": item.volatility_group,
            "regime_group": item.regime_group,
            "category": item.category,
            "name": item.name,
        }
        for item in config.etf_list
        if item.symbol in selected_set
    }

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]
    experiments = portfolio_risk_control_experiments()
    order_names = [item.name for item in experiments]

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
            matrix="portfolio-risk-control",
        )
        result["meta"]["window"] = label
        result["meta"]["baseline_name"] = BASELINE_NAME
        result["meta"]["anchor_name"] = ANCHOR_NAME
        price_map = _load_price_map(selected_codes, start, window_end)
        attribution = {
            name: _attribute_version(item, price_map=price_map, code_meta=code_meta)
            for name, item in result.get("versions", {}).items()
        }
        rows = _rows_from_result(result, attribution, order_names)
        window_results.append({
            "label": label,
            "start": start,
            "end": window_end,
            "rows": rows,
            "decision": _window_decision(rows),
        })

    return {
        "meta": {
            "codes": selected_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "portfolio-risk-control",
            "baseline_name": BASELINE_NAME,
            "anchor_name": ANCHOR_NAME,
        },
        "windows": window_results,
    }


def format_portfolio_risk_control_report(result: dict[str, Any]) -> str:
    """Format portfolio risk-control experiment results."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 150)
    lines.append("  组合风险控制实验报告")
    lines.append("=" * 150)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  单 ETF 基础仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  锚点: 全池质量分层，即 high_vol 使用高波新信号和质量分层仓位，low_vol 保持 baseline-v2.4。")
    lines.append("")

    for window in result.get("windows", []):
        _append_window(lines, window)

    lines.append("  说明:")
    lines.append("  - Δ年化/Δ回撤/较锚Cal 均相对全池质量分层锚点；Δ回撤为正数表示回撤下降。")
    lines.append("  - 现金、总仓、高波和低波为每日收盘持仓市值 / 当日总权益的时间平均。")
    lines.append("  - 拦截表示组合风控完全拒绝买入；缩放表示买入金额被组合风控压低。")
    return "\n".join(lines)


def _rows_from_result(
    result: dict[str, Any],
    attribution: dict[str, dict[str, Any]],
    order_names: list[str],
) -> list[dict[str, Any]]:
    versions = result.get("versions", {})
    rows = []
    seen = set()
    for name in order_names:
        item = versions.get(name)
        if item is None:
            continue
        rows.append(_row_from_version(name, item, attribution.get(name, {})))
        seen.add(name)
    for name, item in versions.items():
        if name in seen:
            continue
        rows.append(_row_from_version(name, item, attribution.get(name, {})))
    return rows


def _row_from_version(name: str, item: dict[str, Any], attr: dict[str, Any]) -> dict[str, Any]:
    exp = item.get("experiment", {})
    return {
        "name": name,
        "label": exp.get("label") or name,
        "summary": item.get("summary", {}),
        "stats": item.get("stats", {}),
        "attribution": attr,
        "has_portfolio_risk": exp.get("portfolio_risk_rule") is not None,
    }


def _append_window(lines: list[str], window: dict[str, Any]) -> None:
    lines.append(f"  区间: {window['label']} ({window['start']} ~ {window['end']})")
    rows = window.get("rows", [])
    _append_metric_table(lines, rows)
    _append_exposure_delta_table(lines, rows)
    _append_trigger_table(lines, rows)
    lines.append(f"  判断: {window.get('decision', '待判断')}")
    lines.append("")


def _append_metric_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    anchor = _row_by_name(rows, ANCHOR_NAME)
    if anchor is None:
        return
    anchor_summary = anchor["summary"]
    headers = ["实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "较锚Cal", "PF", "交易", "现金", "总仓", "高波", "判断"]
    cols = [16, 9, 9, 9, 9, 8, 8, 8, 6, 8, 8, 8, 8]
    lines.append("  收益、回撤与平均暴露")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        summary = row["summary"]
        attr = row["attribution"]
        exposure = attr.get("avg_exposure", {})
        lines.append(
            f"  {row['label'][:16]:16s}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_delta_pct(summary, anchor_summary, 'annual_return', lower_is_better=False):>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {_delta_pct(summary, anchor_summary, 'max_drawdown', lower_is_better=True):>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {_delta_number(summary, anchor_summary, 'calmar'):>8s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {_fmt_pct(attr.get('avg_cash_ratio')):>8s}"
            f" {_fmt_pct(attr.get('avg_market_ratio')):>8s}"
            f" {_fmt_pct(exposure.get('vol:high_vol')):>8s}"
            f" {_row_judgement(row, anchor):>8s}"
        )
    lines.append("")


def _append_exposure_delta_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    anchor = _row_by_name(rows, ANCHOR_NAME)
    if anchor is None:
        return
    headers = ["实验", "Δ现金", "Δ总仓", "Δ高波", "Δ低波"]
    cols = [16, 9, 9, 9, 9]
    lines.append("  相对全池质量分层的暴露变化")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        if row["name"] == ANCHOR_NAME:
            continue
        lines.append(
            f"  {row['label'][:16]:16s}"
            f" {_delta_attr(row, anchor, 'avg_cash_ratio'):>9s}"
            f" {_delta_attr(row, anchor, 'avg_market_ratio'):>9s}"
            f" {_delta_exposure(row, anchor, 'vol:high_vol'):>9s}"
            f" {_delta_exposure(row, anchor, 'vol:low_vol'):>9s}"
        )
    lines.append("")


def _append_trigger_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    headers = ["实验", "拦截", "缩放", "仓数拒", "高波数拒", "单标拒", "单标缩", "总仓拒", "总仓缩", "高波拒", "高波缩"]
    cols = [16, 6, 6, 7, 8, 7, 7, 7, 7, 7, 7]
    lines.append("  风险触发统计")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        stats = row["stats"]
        lines.append(
            f"  {row['label'][:16]:16s}"
            f" {str(stats.get('portfolio_risk_blocked', 0)):>6s}"
            f" {str(stats.get('portfolio_risk_scaled', 0)):>6s}"
            f" {str(stats.get('portfolio_risk_position_count_blocked', 0)):>7s}"
            f" {str(stats.get('portfolio_risk_high_vol_count_blocked', 0)):>8s}"
            f" {str(stats.get('portfolio_risk_single_position_blocked', 0)):>7s}"
            f" {str(stats.get('portfolio_risk_single_position_scaled', 0)):>7s}"
            f" {str(stats.get('portfolio_risk_total_exposure_blocked', 0)):>7s}"
            f" {str(stats.get('portfolio_risk_total_exposure_scaled', 0)):>7s}"
            f" {str(stats.get('portfolio_risk_high_vol_exposure_blocked', 0)):>7s}"
            f" {str(stats.get('portfolio_risk_high_vol_exposure_scaled', 0)):>7s}"
        )
    lines.append("")


def _window_decision(rows: list[dict[str, Any]]) -> str:
    anchor = _row_by_name(rows, ANCHOR_NAME)
    if anchor is None:
        return "待判断"
    candidates = [row for row in rows if row.get("has_portfolio_risk")]
    if not candidates:
        return "待判断"
    ranked = sorted(candidates, key=_rank_key, reverse=True)
    best = ranked[0]
    judgement = _row_judgement(best, anchor)
    if judgement in {"优先", "观察"}:
        return f"{best['label']} 是当前最优组合风控候选，判断为{judgement}。"
    return "暂无组合风控候选优于全池质量分层锚点，继续保留锚点观察。"


def _rank_key(row: dict[str, Any]) -> tuple[float, float, float]:
    summary = row.get("summary", {})
    calmar = _parse_number(summary.get("calmar"))
    annual = _parse_percent(summary.get("annual_return"))
    drawdown = _parse_percent(summary.get("max_drawdown"))
    return (
        calmar if calmar is not None else -999.0,
        annual if annual is not None else -999.0,
        -(drawdown if drawdown is not None else 999.0),
    )


def _row_judgement(row: dict[str, Any], anchor: dict[str, Any]) -> str:
    if row["name"] == BASELINE_NAME:
        return "基线"
    if row["name"] == ANCHOR_NAME:
        return "锚点"
    summary = row["summary"]
    anchor_summary = anchor["summary"]
    annual = _parse_percent(summary.get("annual_return"))
    anchor_annual = _parse_percent(anchor_summary.get("annual_return"))
    drawdown = _parse_percent(summary.get("max_drawdown"))
    anchor_drawdown = _parse_percent(anchor_summary.get("max_drawdown"))
    calmar = _parse_number(summary.get("calmar"))
    anchor_calmar = _parse_number(anchor_summary.get("calmar"))
    if None in (annual, anchor_annual, drawdown, anchor_drawdown, calmar, anchor_calmar):
        return "待判断"
    if calmar > anchor_calmar and annual >= anchor_annual * 0.95 and drawdown <= anchor_drawdown:
        return "优先"
    if drawdown < anchor_drawdown and calmar >= anchor_calmar and annual >= anchor_annual * 0.90:
        return "观察"
    if drawdown < anchor_drawdown and annual < anchor_annual * 0.90:
        return "降险耗收"
    return "不采纳"


def _row_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for row in rows:
        if row["name"] == name:
            return row
    return None


def _metric(summary: dict[str, Any], key: str) -> str:
    return str(summary.get(key, "N/A"))


def _delta_attr(row: dict[str, Any], anchor: dict[str, Any], key: str) -> str:
    current = row["attribution"].get(key)
    base = anchor["attribution"].get(key)
    if current is None or base is None:
        return "N/A"
    return _fmt_pct(current - base, signed=True)


def _delta_exposure(row: dict[str, Any], anchor: dict[str, Any], key: str) -> str:
    current = row["attribution"].get("avg_exposure", {}).get(key)
    base = anchor["attribution"].get("avg_exposure", {}).get(key)
    if current is None or base is None:
        return "N/A"
    return _fmt_pct(current - base, signed=True)


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
        try:
            return float(text[:-1]) / 100
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


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2%}" if signed else f"{value:.2%}"
