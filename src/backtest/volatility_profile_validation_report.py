"""Same-basis validation for volatility-group signal profiles."""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from types import MethodType
from typing import Any

import pandas as pd

from src.backtest.ablation_config import (
    HIGH_VOL_QUALITY_BUDGET_TIER,
    production_v2_4_experiment,
)
from src.backtest.portfolio_backtest import PortfolioBacktest
from src.config import AppConfig
from src.database import indicators_repo, quote_repo
from src.service.calendar_service import TradingCalendarService
from src.strategy import create_strategy


OUT_PATH = Path(__file__).with_name("volatility_profile_validation_report.md")

LOW_VOL_CLUSTER_CODES = {
    "513100", "159611", "159326", "159825",
    "561360", "516970", "159996", "510150",
}
MIGRATED_TO_HIGH_CODES = {"159949", "159870", "515210", "512170", "512880"}

HIGH_BASE_PARAMS = {
    "buy_threshold": 45,
    "sell_threshold": -35,
    "adx_min": 18,
    "min_positive": 3,
}
HIGH_POS4_PARAMS = {**HIGH_BASE_PARAMS, "min_positive": 4}

LOW_DEFAULT_PARAMS: dict[str, Any] | None = None
LOW_BUY45_PARAMS = {"buy_threshold": 45, "sell_threshold": -50, "min_positive": 2}
LOW_BUY40_PARAMS = {"buy_threshold": 40, "sell_threshold": -50, "min_positive": 2}
LOW_RELAXED_PARAMS = {"buy_threshold": 45, "sell_threshold": -45, "min_positive": 1}


@dataclass(frozen=True)
class ValidationSpec:
    """One strategy/grouping candidate in the validation matrix."""

    name: str
    label: str
    grouping: str
    high_params: dict[str, Any]
    low_params: dict[str, Any] | None
    description: str


def run_volatility_profile_validation_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run the agreed volatility-profile validation matrix."""
    from src.config import load_config

    config = load_config()
    selected_codes = codes or [item.symbol for item in config.etf_list]
    selected_set = set(selected_codes)
    current_groups = {
        item.symbol: item.volatility_group
        for item in config.etf_list
        if item.symbol in selected_set
    }
    cluster_groups = _cluster_groups(selected_codes)

    calendar = TradingCalendarService()
    resolved_end = _resolve_common_end(selected_codes, calendar, end)
    windows = _validation_windows(resolved_end)

    main_specs = _main_specs(current_groups, cluster_groups)
    diagnostic_specs = _diagnostic_specs(current_groups, cluster_groups)
    all_specs = {
        spec.name: spec
        for spec in [*main_specs, *diagnostic_specs]
    }

    min_start = min(window["start"] for window in windows)
    signal_cache = {
        name: _generate_signal_frame(
            _config_for_spec(config, spec, current_groups, cluster_groups),
            selected_codes,
            min_start,
            resolved_end,
        )
        for name, spec in all_specs.items()
    }

    main_results = _run_matrix(
        specs=main_specs,
        config=config,
        current_groups=current_groups,
        cluster_groups=cluster_groups,
        signal_cache=signal_cache,
        codes=selected_codes,
        windows=windows,
        capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
    )
    diagnostics = _run_diagnostics(
        specs=diagnostic_specs,
        config=config,
        current_groups=current_groups,
        cluster_groups=cluster_groups,
        signal_cache=signal_cache,
        windows=windows[:2],
        capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
    )

    result = {
        "meta": {
            "codes": selected_codes,
            "current_low_vol_codes": sorted(
                code for code, group in current_groups.items() if group == "low_vol"
            ),
            "current_high_vol_codes": sorted(
                code for code, group in current_groups.items() if group == "high_vol"
            ),
            "cluster_low_vol_codes": sorted(
                code for code, group in cluster_groups.items() if group == "low_vol"
            ),
            "cluster_high_vol_codes": sorted(
                code for code, group in cluster_groups.items() if group == "high_vol"
            ),
            "migrated_to_high_codes": sorted(MIGRATED_TO_HIGH_CODES & selected_set),
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "end": resolved_end,
            "matrix": "volatility-profile-validation",
        },
        "main": main_results,
        "diagnostics": diagnostics,
    }
    report = format_volatility_profile_validation_report(result)
    OUT_PATH.write_text(report, encoding="utf-8")
    return result


def format_volatility_profile_validation_report(result: dict[str, Any]) -> str:
    """Format the validation report as markdown."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("# 波动分组策略同口径验证报告")
    lines.append("")
    lines.append(f"> 输出文件: `{OUT_PATH}`")
    lines.append("")
    lines.append("## 口径")
    lines.append("")
    lines.append(f"- 初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"- 交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"- 单 ETF 仓位上限: {meta['position_limit']:.0%}")
    lines.append("- 门控、70/15/15、high_vol 质量分层预算、分市场/分波动止损和 90 日持有期保持一致")
    lines.append("- 新聚类分组只改变 `volatility_group` 对信号分发和 high_vol 质量分层预算的影响，不同步改止损 profile")
    lines.append("")
    lines.append("## 分组")
    lines.append("")
    lines.append(f"- 当前 high_vol: {', '.join(meta['current_high_vol_codes'])}")
    lines.append(f"- 当前 low_vol: {', '.join(meta['current_low_vol_codes'])}")
    lines.append(f"- 聚类 high_vol: {', '.join(meta['cluster_high_vol_codes'])}")
    lines.append(f"- 聚类 low_vol: {', '.join(meta['cluster_low_vol_codes'])}")
    lines.append(f"- 从 low_vol 迁到 high_vol: {', '.join(meta['migrated_to_high_codes'])}")
    lines.append("")

    lines.append("## 主实验")
    lines.append("")
    for window in result.get("main", []):
        _append_window_table(lines, window)

    lines.append("## 诊断实验")
    lines.append("")
    _append_diagnostic_block(lines, "高波 19 只", result["diagnostics"].get("high_vol", []))
    _append_diagnostic_block(lines, "低波 8 只", result["diagnostics"].get("low_vol", []))
    _append_diagnostic_block(lines, "迁移 5 只", result["diagnostics"].get("migrated", []))

    lines.append("## 结论规则")
    lines.append("")
    lines.append("- 主候选必须在全池相对 `P0 当前生产` 达到年化相对提升 >= 5%、最大回撤相对下降 >= 5%。")
    lines.append("- 胜率绝对提升 >= 3pct 是强采纳条件；若收益和回撤显著改善但胜率未达标，标记为有争议候选。")
    lines.append("- Calmar、Sharpe、利润因子不得明显恶化。")
    return "\n".join(lines)


def _main_specs(
    current_groups: dict[str, str],
    cluster_groups: dict[str, str],
) -> list[ValidationSpec]:
    return [
        ValidationSpec(
            name="p0_current_v25",
            label="P0 当前生产",
            grouping="current",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="M0 + H0 + L0",
        ),
        ValidationSpec(
            name="p1_cluster_groups",
            label="P1 仅新分组",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="M1 + H0 + L0",
        ),
        ValidationSpec(
            name="p2_high_pos4_current",
            label="P2 仅高波收紧",
            grouping="current",
            high_params=HIGH_POS4_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="M0 + H1 + L0",
        ),
        ValidationSpec(
            name="p3_cluster_high_pos4",
            label="P3 主候选",
            grouping="cluster",
            high_params=HIGH_POS4_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="M1 + H1 + L0",
        ),
        ValidationSpec(
            name="p4_cluster_low_buy45",
            label="P4 低波BUY45",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_BUY45_PARAMS,
            description="M1 + H0 + L1",
        ),
        ValidationSpec(
            name="p5_cluster_high_pos4_low_buy45",
            label="P5 主候选+低波BUY45",
            grouping="cluster",
            high_params=HIGH_POS4_PARAMS,
            low_params=LOW_BUY45_PARAMS,
            description="M1 + H1 + L1",
        ),
    ]


def _diagnostic_specs(
    current_groups: dict[str, str],
    cluster_groups: dict[str, str],
) -> list[ValidationSpec]:
    return [
        ValidationSpec(
            name="diag_h0_cluster",
            label="H0 正子>=3",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="高波诊断对照",
        ),
        ValidationSpec(
            name="diag_h1_cluster",
            label="H1 正子>=4",
            grouping="cluster",
            high_params=HIGH_POS4_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="高波诊断候选",
        ),
        ValidationSpec(
            name="diag_l0_cluster",
            label="L0 默认",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="低波诊断对照",
        ),
        ValidationSpec(
            name="diag_l1_buy45",
            label="L1 BUY45",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_BUY45_PARAMS,
            description="低波 BUY=45",
        ),
        ValidationSpec(
            name="diag_l2_buy40",
            label="L2 BUY40",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_BUY40_PARAMS,
            description="低波 BUY=40",
        ),
        ValidationSpec(
            name="diag_l3_relaxed",
            label="L3 宽松",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_RELAXED_PARAMS,
            description="低波 BUY=45/SELL=-45/正子>=1",
        ),
        ValidationSpec(
            name="diag_migrated_low",
            label="迁移前低波处理",
            grouping="current",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="迁移 ETF 按当前 low_vol 处理",
        ),
        ValidationSpec(
            name="diag_migrated_high_h0",
            label="迁移后H0",
            grouping="cluster",
            high_params=HIGH_BASE_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="迁移 ETF 按 high_vol H0 处理",
        ),
        ValidationSpec(
            name="diag_migrated_high_h1",
            label="迁移后H1",
            grouping="cluster",
            high_params=HIGH_POS4_PARAMS,
            low_params=LOW_DEFAULT_PARAMS,
            description="迁移 ETF 按 high_vol H1 处理",
        ),
    ]


def _run_matrix(
    *,
    specs: list[ValidationSpec],
    config: AppConfig,
    current_groups: dict[str, str],
    cluster_groups: dict[str, str],
    signal_cache: dict[str, pd.DataFrame],
    codes: list[str],
    windows: list[dict[str, Any]],
    capital: float,
    cost_ratio: float,
    slippage: float,
    position_limit: float,
) -> list[dict[str, Any]]:
    results = []
    for window in windows:
        rows = []
        for spec in specs:
            row = _run_one(
                spec=spec,
                config=config,
                current_groups=current_groups,
                cluster_groups=cluster_groups,
                signal_df=signal_cache[spec.name],
                codes=codes,
                start=window["start"],
                end=window["end"],
                capital=capital,
                cost_ratio=cost_ratio,
                slippage=slippage,
                position_limit=position_limit,
            )
            rows.append(row)
        results.append({
            **window,
            "rows": rows,
            "decision": _decision(rows),
        })
    return results


def _run_diagnostics(
    *,
    specs: list[ValidationSpec],
    config: AppConfig,
    current_groups: dict[str, str],
    cluster_groups: dict[str, str],
    signal_cache: dict[str, pd.DataFrame],
    windows: list[dict[str, Any]],
    capital: float,
    cost_ratio: float,
    slippage: float,
    position_limit: float,
) -> dict[str, list[dict[str, Any]]]:
    selected = {
        "high_vol": (
            ["diag_h0_cluster", "diag_h1_cluster"],
            sorted(code for code, group in cluster_groups.items() if group == "high_vol"),
        ),
        "low_vol": (
            ["diag_l0_cluster", "diag_l1_buy45", "diag_l2_buy40", "diag_l3_relaxed"],
            sorted(code for code, group in cluster_groups.items() if group == "low_vol"),
        ),
        "migrated": (
            ["diag_migrated_low", "diag_migrated_high_h0", "diag_migrated_high_h1"],
            sorted(MIGRATED_TO_HIGH_CODES & set(cluster_groups)),
        ),
    }
    by_name = {spec.name: spec for spec in specs}
    output: dict[str, list[dict[str, Any]]] = {}
    for block_name, (spec_names, codes) in selected.items():
        block_windows = []
        if not codes:
            output[block_name] = block_windows
            continue
        for window in windows:
            rows = []
            for spec_name in spec_names:
                spec = by_name[spec_name]
                rows.append(_run_one(
                    spec=spec,
                    config=config,
                    current_groups=current_groups,
                    cluster_groups=cluster_groups,
                    signal_df=signal_cache[spec.name],
                    codes=codes,
                    start=window["start"],
                    end=window["end"],
                    capital=capital,
                    cost_ratio=cost_ratio,
                    slippage=slippage,
                    position_limit=position_limit,
                ))
            block_windows.append({**window, "codes": codes, "rows": rows})
        output[block_name] = block_windows
    return output


def _run_one(
    *,
    spec: ValidationSpec,
    config: AppConfig,
    current_groups: dict[str, str],
    cluster_groups: dict[str, str],
    signal_df: pd.DataFrame,
    codes: list[str],
    start: date,
    end: date,
    capital: float,
    cost_ratio: float,
    slippage: float,
    position_limit: float,
) -> dict[str, Any]:
    group_map = _groups_for_spec(spec, current_groups, cluster_groups)
    calendar = TradingCalendarService()
    bt = PortfolioBacktest(
        calendar=calendar,
        initial_capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        cooldown_days=config.strategy_params.get("cooldown_days", 5),
        market_regime_params=config.market_regime_params,
        code_regime_groups={item.symbol: item.regime_group for item in config.etf_list},
        code_stop_loss_profiles={item.symbol: item.stop_loss_profile for item in config.etf_list},
        code_volatility_groups=group_map,
    )

    def _load_unified_signals(self, target_codes: list[str], s: date, e: date) -> pd.DataFrame:
        return _filter_signal_frame(signal_df, target_codes, s, e)

    bt._load_unified_signals = MethodType(_load_unified_signals, bt)
    experiment = production_v2_4_experiment(
        name=spec.name,
        label=spec.label,
        high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
        description=spec.description,
    )
    result = bt.run_experiments(codes=codes, start=start, end=end, experiments=[experiment])
    version = result.get("versions", {}).get(spec.name, {})
    summary = version.get("summary", {})
    stats = version.get("stats", {})
    signals = _filter_signal_frame(signal_df, codes, start, end)
    signal_counts = signals["signal"].value_counts().to_dict() if not signals.empty else {}
    return {
        "name": spec.name,
        "label": spec.label,
        "description": spec.description,
        "summary": summary,
        "stats": stats,
        "signal_counts": signal_counts,
    }


def _generate_signal_frame(
    config: AppConfig,
    codes: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    strategy = create_strategy(config)
    rows = []
    for code in codes:
        indicators = indicators_repo.find_by_code_between(code, start, end)
        quotes = quote_repo.find_by_code_in_range(code, start, end)
        close_map = {str(quote.date): quote.close for quote in quotes}
        for ind in indicators:
            row = {"code": ind.code, "date": str(ind.date)}
            row.update(ind.data)
            row["close"] = close_map.get(str(ind.date))
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["code", "date", "signal", "signal_meta"])
    df = pd.DataFrame(rows)
    signal_df = strategy.generate(df)
    signal_df["date"] = signal_df["date"].astype(str)
    return signal_df[["code", "date", "signal", "signal_meta"]].copy()


def _filter_signal_frame(
    signal_df: pd.DataFrame,
    codes: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    if signal_df.empty:
        return pd.DataFrame(columns=["code", "date", "signal", "signal_meta"])
    work = signal_df[signal_df["code"].isin(codes)].copy()
    work["_date"] = pd.to_datetime(work["date"]).dt.date
    work = work[(work["_date"] >= start) & (work["_date"] <= end)]
    work = work.drop(columns=["_date"])
    return work.sort_values(["code", "date"]).reset_index(drop=True)


def _config_for_spec(
    config: AppConfig,
    spec: ValidationSpec,
    current_groups: dict[str, str],
    cluster_groups: dict[str, str],
) -> AppConfig:
    group_map = _groups_for_spec(spec, current_groups, cluster_groups)
    etf_list = [
        replace(item, volatility_group=group_map.get(item.symbol, item.volatility_group))
        for item in config.etf_list
    ]
    params = deepcopy(config.strategy_params)
    params["volatility_signal_profiles"] = {
        "high_vol": {
            "enabled": True,
            "kind": "high_vol_balanced",
            "params": dict(spec.high_params),
        }
    }
    if spec.low_params is not None:
        params["volatility_signal_profiles"]["low_vol"] = {
            "enabled": True,
            "kind": "relaxed_default",
            "params": dict(spec.low_params),
        }
    else:
        params["volatility_signal_profiles"]["low_vol"] = {"enabled": False, "kind": None, "params": {}}
    return replace(config, etf_list=etf_list, strategy_params=params)


def _groups_for_spec(
    spec: ValidationSpec,
    current_groups: dict[str, str],
    cluster_groups: dict[str, str],
) -> dict[str, str]:
    if spec.grouping == "current":
        return dict(current_groups)
    if spec.grouping == "cluster":
        return dict(cluster_groups)
    raise ValueError(f"未知分组口径: {spec.grouping}")


def _cluster_groups(codes: list[str]) -> dict[str, str]:
    return {
        code: ("low_vol" if code in LOW_VOL_CLUSTER_CODES else "high_vol")
        for code in codes
    }


def _resolve_common_end(
    codes: list[str],
    calendar: TradingCalendarService,
    requested_end: date | None,
) -> date:
    latest_dates = [quote_repo.find_latest_date(code) for code in codes]
    latest_dates = [item for item in latest_dates if item is not None]
    if not latest_dates:
        raise ValueError("没有可用 quote 数据，无法确定共同回测结束日")
    end = min(latest_dates)
    previous_trading_day = date.fromisoformat(calendar.get_previous_trading_day())
    end = min(end, previous_trading_day)
    if requested_end is not None:
        end = min(end, requested_end)
    return end


def _validation_windows(end: date) -> list[dict[str, Any]]:
    candidates = [
        {"label": "2016-2026", "start": date(2016, 1, 1), "end": end},
        {"label": "2024-2026", "start": date(2024, 1, 1), "end": end},
        {"label": "2024-06锚点", "start": date(2024, 6, 1), "end": min(end, date(2026, 6, 3))},
    ]
    return [item for item in candidates if item["start"] <= item["end"]]


def _append_window_table(lines: list[str], window: dict[str, Any]) -> None:
    rows = window.get("rows", [])
    baseline = _row_by_name(rows, "p0_current_v25")
    lines.append(f"### {window['label']} ({window['start']} ~ {window['end']})")
    lines.append("")
    lines.append("| 实验 | 说明 | 年化 | Δ年化 | 回撤 | Δ回撤 | Calmar | Sharpe | 胜率 | Δ胜率 | PF | 交易 | BUY | SELL | 判断 |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        summary = row["summary"]
        counts = row.get("signal_counts", {})
        lines.append(
            f"| {row['label']} | {row['description']} "
            f"| {_metric(summary, 'annual_return')} | {_delta_pct(row, baseline, 'annual_return', lower_is_better=False)} "
            f"| {_metric(summary, 'max_drawdown')} | {_delta_pct(row, baseline, 'max_drawdown', lower_is_better=True)} "
            f"| {_metric(summary, 'calmar')} | {_metric(summary, 'sharpe')} "
            f"| {_metric(summary, 'win_rate')} | {_delta_pct(row, baseline, 'win_rate', lower_is_better=False)} "
            f"| {_metric(summary, 'profit_factor')} | {_metric(summary, 'total_trades')} "
            f"| {counts.get('BUY', 0)} | {counts.get('SELL', 0)} | {_row_decision(row, baseline)} |"
        )
    lines.append("")
    lines.append(f"窗口判断: {window.get('decision', '待判断')}")
    lines.append("")


def _append_diagnostic_block(
    lines: list[str],
    title: str,
    windows: list[dict[str, Any]],
) -> None:
    lines.append(f"### {title}")
    lines.append("")
    for window in windows:
        rows = window.get("rows", [])
        baseline = rows[0] if rows else None
        lines.append(
            f"#### {window['label']} ({window['start']} ~ {window['end']}), "
            f"ETF={len(window.get('codes', []))}"
        )
        lines.append("")
        lines.append("| 实验 | 年化 | Δ年化 | 回撤 | Δ回撤 | Calmar | Sharpe | 胜率 | PF | 交易 | 止损 | BUY | SELL |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for row in rows:
            summary = row["summary"]
            stats = row.get("stats", {})
            counts = row.get("signal_counts", {})
            lines.append(
                f"| {row['label']} | {_metric(summary, 'annual_return')} "
                f"| {_delta_pct(row, baseline, 'annual_return', lower_is_better=False)} "
                f"| {_metric(summary, 'max_drawdown')} "
                f"| {_delta_pct(row, baseline, 'max_drawdown', lower_is_better=True)} "
                f"| {_metric(summary, 'calmar')} | {_metric(summary, 'sharpe')} "
                f"| {_metric(summary, 'win_rate')} | {_metric(summary, 'profit_factor')} "
                f"| {_metric(summary, 'total_trades')} | {stats.get('stop_loss_triggered', 0)} "
                f"| {counts.get('BUY', 0)} | {counts.get('SELL', 0)} |"
            )
        lines.append("")


def _decision(rows: list[dict[str, Any]]) -> str:
    baseline = _row_by_name(rows, "p0_current_v25")
    candidate = _row_by_name(rows, "p3_cluster_high_pos4")
    if baseline is None or candidate is None:
        return "待判断"
    return _row_decision(candidate, baseline)


def _row_decision(row: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    if baseline is None or row is baseline:
        return "对照"
    annual = _parse_percent(row["summary"].get("annual_return"))
    base_annual = _parse_percent(baseline["summary"].get("annual_return"))
    drawdown = _parse_percent(row["summary"].get("max_drawdown"))
    base_drawdown = _parse_percent(baseline["summary"].get("max_drawdown"))
    win = _parse_percent(row["summary"].get("win_rate"))
    base_win = _parse_percent(baseline["summary"].get("win_rate"))
    calmar = _parse_number(row["summary"].get("calmar"))
    base_calmar = _parse_number(baseline["summary"].get("calmar"))
    sharpe = _parse_number(row["summary"].get("sharpe"))
    base_sharpe = _parse_number(baseline["summary"].get("sharpe"))
    pf = _parse_number(row["summary"].get("profit_factor"))
    base_pf = _parse_number(baseline["summary"].get("profit_factor"))
    if None in (
        annual, base_annual, drawdown, base_drawdown,
        win, base_win, calmar, base_calmar, sharpe, base_sharpe, pf, base_pf,
    ):
        return "待判断"
    annual_ok = base_annual != 0 and (annual - base_annual) / abs(base_annual) >= 0.05
    drawdown_ok = base_drawdown != 0 and (base_drawdown - drawdown) / abs(base_drawdown) >= 0.05
    win_ok = win - base_win >= 0.03
    no_obvious_worse = calmar >= base_calmar * 0.95 and sharpe >= base_sharpe * 0.95 and pf >= base_pf * 0.95
    if annual_ok and drawdown_ok and win_ok and no_obvious_worse:
        return "可采纳"
    if annual_ok and drawdown_ok and no_obvious_worse:
        return "有争议"
    return "不采纳"


def _row_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for row in rows:
        if row["name"] == name:
            return row
    return None


def _metric(summary: dict[str, Any], key: str) -> str:
    return str(summary.get(key, "N/A"))


def _delta_pct(
    row: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
    key: str,
    *,
    lower_is_better: bool,
) -> str:
    if row is None or baseline is None or row is baseline:
        return "-"
    current = _parse_percent(row["summary"].get(key))
    base = _parse_percent(baseline["summary"].get(key))
    if current is None or base is None:
        return "N/A"
    delta = base - current if lower_is_better else current - base
    return f"{delta * 100:+.2f}%"


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
