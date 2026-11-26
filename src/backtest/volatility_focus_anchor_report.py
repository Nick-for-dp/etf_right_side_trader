"""Low-volatility focus anchor experiment."""

from datetime import date
from typing import Any

from src.backtest.ablation_config import (
    HIGH_VOL_QUALITY_BUDGET_TIER,
    SIGNAL_PROFILE_HIGH_VOL_BALANCED,
    HighVolFrequencyControlRuleConfig,
    production_v2_4_experiment,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.backtest.high_vol_quality_capital_attribution_report import (
    _attribute_version,
    _load_price_map,
)
from src.service.calendar_service import TradingCalendarService

BASELINE_NAME = "baseline_v2_4_segment_stop"
LOW_ONLY_NAME = "low_vol_only"
HIGH_ONLY_NAME = "high_vol_only"
SATELLITE_NAME = "low_vol_core_high_vol_satellite"
TIER_NAME = "high_vol_quality_budget_tier"


def run_volatility_focus_anchor_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
    max_satellite_high_vol_positions: int = 3,
) -> dict[str, Any]:
    """Run the low/high volatility focus anchor matrix."""
    from src.config import load_config

    config = load_config()
    selected_codes = codes or [item.symbol for item in config.etf_list]
    selected_set = set(selected_codes)
    low_codes = [
        item.symbol for item in config.etf_list
        if item.symbol in selected_set and item.volatility_group == "low_vol"
    ]
    high_codes = [
        item.symbol for item in config.etf_list
        if item.symbol in selected_set and item.volatility_group == "high_vol"
    ]
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
    full_experiments, low_experiments, high_experiments = _anchor_experiments(
        max_satellite_high_vol_positions=max_satellite_high_vol_positions,
    )

    window_results = []
    for label, start, window_end in windows:
        price_map = _load_price_map(selected_codes, start, window_end)
        rows = []
        rows.extend(_run_rows(
            codes=selected_codes,
            start=start,
            end=window_end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=full_experiments,
            matrix="volatility-focus-anchor",
            scope="全池",
            codes_count=len(selected_codes),
            price_map=price_map,
            code_meta=code_meta,
        ))
        rows.extend(_run_rows(
            codes=low_codes,
            start=start,
            end=window_end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=low_experiments,
            matrix="volatility-focus-anchor-low",
            scope="低波",
            codes_count=len(low_codes),
            price_map=price_map,
            code_meta=code_meta,
        ))
        rows.extend(_run_rows(
            codes=high_codes,
            start=start,
            end=window_end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=high_experiments,
            matrix="volatility-focus-anchor-high",
            scope="高波",
            codes_count=len(high_codes),
            price_map=price_map,
            code_meta=code_meta,
        ))
        ordered_rows = _order_rows(rows)
        window_results.append({
            "label": label,
            "start": start,
            "end": window_end,
            "rows": ordered_rows,
            "decision": _window_decision(ordered_rows),
        })

    return {
        "meta": {
            "codes": selected_codes,
            "low_vol_codes": low_codes,
            "high_vol_codes": high_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "max_satellite_high_vol_positions": max_satellite_high_vol_positions,
            "matrix": "volatility-focus-anchor",
        },
        "windows": window_results,
    }


def format_volatility_focus_anchor_report(result: dict[str, Any]) -> str:
    """Format the volatility focus anchor report."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 150)
    lines.append("  低波/高波策略重心锚点实验报告")
    lines.append("=" * 150)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  单 ETF 仓位上限: {meta['position_limit']:.0%}")
    lines.append(
        "  ETF 数量: "
        f"全池 {len(meta['codes'])} / 低波 {len(meta['low_vol_codes'])} / 高波 {len(meta['high_vol_codes'])}"
    )
    lines.append(
        "  低波核心+高波卫星: high_vol 使用新底层信号和质量分层仓位，"
        f"同时高波最多持有 {meta['max_satellite_high_vol_positions']} 只。"
    )
    lines.append("")

    for window in result.get("windows", []):
        _append_window(lines, window)

    lines.append("  说明:")
    lines.append("  - 低波单独/高波单独均使用 100,000 元初始资金，比较的是不同 ETF universe 的资金效率。")
    lines.append("  - 暴露为每日收盘持仓市值 / 当日总权益的时间平均。")
    lines.append("  - Δ回撤为相对全池质量分层的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def _anchor_experiments(
    *,
    max_satellite_high_vol_positions: int,
) -> tuple[list[Any], list[Any], list[Any]]:
    satellite_rule = HighVolFrequencyControlRuleConfig(
        name="high_vol_satellite_max_positions",
        label=f"高波最多{max_satellite_high_vol_positions}只",
        max_high_vol_positions=max_satellite_high_vol_positions,
        description=f"低波核心实验中 high_vol 同时持仓最多 {max_satellite_high_vol_positions} 只。",
    )
    full_experiments = [
        production_v2_4_experiment(
            name=BASELINE_NAME,
            label="baseline-v2.4",
            description="全池对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name=SATELLITE_NAME,
            label="低波核心+高波卫星",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
            high_vol_frequency_rule=satellite_rule,
            description=(
                "low_vol 沿用 baseline-v2.4；high_vol 使用高波新底层信号、"
                "质量分层仓位，并限制高波同时持仓数。"
            ),
        ),
        production_v2_4_experiment(
            name=TIER_NAME,
            label="全池质量分层",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
            description="high_vol 使用新底层信号和质量分层仓位，low_vol 保持 baseline-v2.4。",
        ),
    ]
    low_experiments = [
        production_v2_4_experiment(
            name=LOW_ONLY_NAME,
            label="低波单独",
            description="只交易 low_vol ETF，信号、门控、风控和执行沿用 baseline-v2.4。",
        ),
    ]
    high_experiments = [
        production_v2_4_experiment(
            name=HIGH_ONLY_NAME,
            label="高波单独",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
            description="只交易 high_vol ETF，并使用高波新底层信号和质量分层仓位。",
        ),
    ]
    return full_experiments, low_experiments, high_experiments


def _run_rows(
    *,
    codes: list[str],
    start: date,
    end: date,
    capital: float,
    cost_ratio: float,
    slippage: float,
    position_limit: float,
    experiments: list[Any],
    matrix: str,
    scope: str,
    codes_count: int,
    price_map: dict[str, dict[str, float]],
    code_meta: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    if not codes:
        return []
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
    return _rows_from_result(
        result,
        scope=scope,
        codes_count=codes_count,
        price_map=price_map,
        code_meta=code_meta,
    )


def _rows_from_result(
    result: dict[str, Any],
    *,
    scope: str,
    codes_count: int,
    price_map: dict[str, dict[str, float]],
    code_meta: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    rows = []
    for name, item in result.get("versions", {}).items():
        attr = _attribute_version(item, price_map=price_map, code_meta=code_meta)
        exp = item.get("experiment", {})
        rows.append({
            "name": name,
            "label": exp.get("label") or name,
            "scope": scope,
            "codes_count": codes_count,
            "summary": item.get("summary", {}),
            "stats": item.get("stats", {}),
            "attribution": attr,
        })
    return rows


def _append_window(lines: list[str], window: dict[str, Any]) -> None:
    lines.append(f"  区间: {window['label']} ({window['start']} ~ {window['end']})")
    rows = window.get("rows", [])
    _append_main_table(lines, rows)
    _append_delta_table(lines, rows)
    lines.append(f"  判断: {window.get('decision', '待判断')}")
    lines.append("")


def _append_main_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    headers = ["实验", "池", "ETF", "年化", "回撤", "Calmar", "Sharpe", "胜率", "PF", "交易", "现金", "高波", "低波"]
    cols = [18, 6, 4, 9, 9, 8, 8, 9, 8, 6, 8, 8, 8]
    lines.append("  策略重心对比")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        summary = row["summary"]
        attr = row["attribution"]
        exposure = attr.get("avg_exposure", {})
        lines.append(
            f"  {row['label'][:18]:18s}"
            f" {row['scope'][:6]:6s}"
            f" {row['codes_count']:>4d}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {summary.get('sharpe', 'N/A'):>8s}"
            f" {_metric(summary, 'win_rate'):>9s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {_fmt_pct(attr.get('avg_cash_ratio')):>8s}"
            f" {_fmt_pct(exposure.get('vol:high_vol')):>8s}"
            f" {_fmt_pct(exposure.get('vol:low_vol')):>8s}"
        )
    lines.append("")


def _append_delta_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    tier = _row_by_name(rows, TIER_NAME)
    if tier is None:
        return
    headers = ["实验", "Δ年化", "Δ回撤", "ΔCalmar", "Δ高波暴露", "Δ低波暴露"]
    cols = [18, 9, 9, 9, 11, 11]
    lines.append("  相对全池质量分层")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        if row["name"] == TIER_NAME:
            continue
        lines.append(
            f"  {row['label'][:18]:18s}"
            f" {_delta_pct(row['summary'], tier['summary'], 'annual_return', lower_is_better=False):>9s}"
            f" {_delta_pct(row['summary'], tier['summary'], 'max_drawdown', lower_is_better=True):>9s}"
            f" {_delta_number(row['summary'], tier['summary'], 'calmar'):>9s}"
            f" {_delta_exposure(row, tier, 'vol:high_vol'):>11s}"
            f" {_delta_exposure(row, tier, 'vol:low_vol'):>11s}"
        )
    lines.append("")


def _window_decision(rows: list[dict[str, Any]]) -> str:
    low = _row_by_name(rows, LOW_ONLY_NAME)
    high = _row_by_name(rows, HIGH_ONLY_NAME)
    satellite = _row_by_name(rows, SATELLITE_NAME)
    tier = _row_by_name(rows, TIER_NAME)
    if low is None or high is None or satellite is None or tier is None:
        return "待判断"

    low_calmar = _parse_number(low["summary"].get("calmar"))
    high_calmar = _parse_number(high["summary"].get("calmar"))
    satellite_calmar = _parse_number(satellite["summary"].get("calmar"))
    tier_calmar = _parse_number(tier["summary"].get("calmar"))
    low_annual = _parse_percent(low["summary"].get("annual_return"))
    tier_annual = _parse_percent(tier["summary"].get("annual_return"))
    if None in (low_calmar, high_calmar, satellite_calmar, tier_calmar, low_annual, tier_annual):
        return "待判断"

    if low_calmar >= tier_calmar and low_annual >= tier_annual * 0.9:
        return "低波单独可作为主线锚点，高波可降级为观察池。"
    if satellite_calmar >= tier_calmar and satellite_calmar >= low_calmar:
        return "低波核心+高波卫星优于纯低波，可作为主线锚点。"
    if low_calmar > high_calmar:
        return "低波资金效率优于高波，但仍需和全池质量分层共同观察。"
    return "高波仍有阶段性价值，暂不宜舍弃。"


def _order_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {
        BASELINE_NAME: 0,
        LOW_ONLY_NAME: 1,
        HIGH_ONLY_NAME: 2,
        SATELLITE_NAME: 3,
        TIER_NAME: 4,
    }
    return sorted(rows, key=lambda row: order.get(row["name"], 99))


def _row_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for row in rows:
        if row["name"] == name:
            return row
    return None


def _metric(summary: dict[str, Any], key: str) -> str:
    return str(summary.get(key, "N/A"))


def _delta_exposure(row: dict[str, Any], base: dict[str, Any], key: str) -> str:
    current = row["attribution"].get("avg_exposure", {}).get(key, 0.0)
    baseline = base["attribution"].get("avg_exposure", {}).get(key, 0.0)
    return _fmt_pct(current - baseline, signed=True)


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


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2%}" if signed else f"{value:.2%}"
