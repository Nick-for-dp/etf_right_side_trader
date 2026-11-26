"""Ablation backtest runner and report formatter."""

from datetime import date, timedelta
from statistics import median
from typing import Any

from src.backtest.ablation_config import (
    AblationExperimentConfig,
    get_ablation_experiments,
)
from src.backtest.portfolio_backtest import PortfolioBacktest
from src.backtest.portfolio_metrics import pair_closed_trades
from src.database import indicators_repo
from src.service.calendar_service import TradingCalendarService


def run_ablation_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
    experiments: list[AblationExperimentConfig] | None = None,
    matrix: str = "default",
) -> dict[str, Any]:
    """Run the default ablation experiment matrix."""

    from src.config import load_config

    config = load_config()
    if codes is None:
        codes = [e.symbol for e in config.etf_list]
    code_regime_groups = {e.symbol: e.regime_group for e in config.etf_list}
    code_stop_loss_profiles = {e.symbol: e.stop_loss_profile for e in config.etf_list}
    code_volatility_groups = {e.symbol: e.volatility_group for e in config.etf_list}

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())
    if start is None:
        start = end - timedelta(days=config.lookback_days)

    baseline_name = "baseline_full_gate"
    if experiments is None:
        experiments, baseline_name = get_ablation_experiments(matrix)

    bt = PortfolioBacktest(
        calendar=calendar,
        initial_capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        cooldown_days=config.strategy_params.get("cooldown_days", 5),
        market_regime_params=config.market_regime_params,
        code_regime_groups=code_regime_groups,
        code_stop_loss_profiles=code_stop_loss_profiles,
        code_volatility_groups=code_volatility_groups,
    )
    result = bt.run_experiments(
        codes=codes,
        start=start,
        end=end,
        experiments=experiments,
    )
    result["meta"]["matrix"] = matrix
    result["meta"]["baseline_name"] = baseline_name
    return result


def run_candidate_comparison_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run candidate comparison over the long and recent validation windows."""

    from src.config import load_config

    config = load_config()
    if codes is None:
        codes = [e.symbol for e in config.etf_list]

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    experiments, baseline_name = get_ablation_experiments("candidate-comparison")
    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]

    results = []
    for label, start, window_end in windows:
        result = run_ablation_backtest(
            codes=codes,
            start=start,
            end=window_end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=experiments,
            matrix="candidate-comparison",
        )
        result["meta"]["window"] = label
        result["meta"]["baseline_name"] = baseline_name
        results.append(result)

    return {
        "meta": {
            "codes": codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "candidate-comparison",
            "baseline_name": baseline_name,
            "windows": [
                {"label": label, "start": str(start), "end": str(window_end)}
                for label, start, window_end in windows
            ],
        },
        "windows": results,
    }


def run_reentry_rules_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run stop-loss reentry rule ablation over long and recent windows."""

    from src.config import load_config

    config = load_config()
    if codes is None:
        codes = [e.symbol for e in config.etf_list]

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    experiments, baseline_name = get_ablation_experiments("reentry-rules")
    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]

    results = []
    for label, start, window_end in windows:
        result = run_ablation_backtest(
            codes=codes,
            start=start,
            end=window_end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=experiments,
            matrix="reentry-rules",
        )
        result["meta"]["window"] = label
        result["meta"]["baseline_name"] = baseline_name
        results.append(result)

    return {
        "meta": {
            "codes": codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "reentry-rules",
            "baseline_name": baseline_name,
            "windows": [
                {"label": label, "start": str(start), "end": str(window_end)}
                for label, start, window_end in windows
            ],
        },
        "windows": results,
    }


def run_trend_reentry_segments_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run baseline-v2.4 vs trend-repair by market/volatility segments."""

    from src.config import load_config

    config = load_config()
    selected_codes = codes or [e.symbol for e in config.etf_list]
    selected_set = set(selected_codes)

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    experiments, baseline_name = get_ablation_experiments("trend-reentry-segments")
    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]
    segments = _build_config_segments(config.etf_list, selected_set)

    window_results = []
    for label, start, window_end in windows:
        segment_results = []
        for segment in segments:
            segment_codes = segment["codes"]
            result = run_ablation_backtest(
                codes=segment_codes,
                start=start,
                end=window_end,
                capital=capital,
                cost_ratio=cost_ratio,
                slippage=slippage,
                position_limit=position_limit,
                experiments=experiments,
                matrix="trend-reentry-segments",
            )
            result["meta"]["baseline_name"] = baseline_name
            segment_results.append({**segment, "result": result})
        window_results.append({
            "label": label,
            "start": str(start),
            "end": str(window_end),
            "segments": segment_results,
        })

    return {
        "meta": {
            "codes": selected_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "trend-reentry-segments",
            "baseline_name": baseline_name,
        },
        "windows": window_results,
    }


def run_high_vol_reentry_cooldown_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run high-volatility reentry cooldown experiments by segment."""

    from src.config import load_config

    config = load_config()
    selected_codes = codes or [e.symbol for e in config.etf_list]
    selected_set = set(selected_codes)

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    experiments, baseline_name = get_ablation_experiments("high-vol-reentry-cooldown")
    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]
    segments = _build_config_segments(config.etf_list, selected_set)

    window_results = []
    for label, start, window_end in windows:
        segment_results = []
        for segment in segments:
            result = run_ablation_backtest(
                codes=segment["codes"],
                start=start,
                end=window_end,
                capital=capital,
                cost_ratio=cost_ratio,
                slippage=slippage,
                position_limit=position_limit,
                experiments=experiments,
                matrix="high-vol-reentry-cooldown",
            )
            result["meta"]["baseline_name"] = baseline_name
            segment_results.append({**segment, "result": result})
        window_results.append({
            "label": label,
            "start": str(start),
            "end": str(window_end),
            "segments": segment_results,
        })

    return {
        "meta": {
            "codes": selected_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "high-vol-reentry-cooldown",
            "baseline_name": baseline_name,
        },
        "windows": window_results,
    }


def run_high_vol_reentry_stop_price_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run high-volatility stop-price reclaim reentry experiments by segment."""

    from src.config import load_config

    config = load_config()
    selected_codes = codes or [e.symbol for e in config.etf_list]
    selected_set = set(selected_codes)

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    experiments, baseline_name = get_ablation_experiments("high-vol-reentry-stop-price")
    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]
    segments = _build_config_segments(config.etf_list, selected_set)

    window_results = []
    for label, start, window_end in windows:
        segment_results = []
        for segment in segments:
            result = run_ablation_backtest(
                codes=segment["codes"],
                start=start,
                end=window_end,
                capital=capital,
                cost_ratio=cost_ratio,
                slippage=slippage,
                position_limit=position_limit,
                experiments=experiments,
                matrix="high-vol-reentry-stop-price",
            )
            result["meta"]["baseline_name"] = baseline_name
            segment_results.append({**segment, "result": result})
        window_results.append({
            "label": label,
            "start": str(start),
            "end": str(window_end),
            "segments": segment_results,
        })

    return {
        "meta": {
            "codes": selected_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "high-vol-reentry-stop-price",
            "baseline_name": baseline_name,
        },
        "windows": window_results,
    }


def run_segmented_stop_loss_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run stop-loss ablation by market and volatility segments."""

    from src.config import load_config

    config = load_config()
    if codes is None:
        codes = [e.symbol for e in config.etf_list]
    code_regime_groups = {e.symbol: e.regime_group for e in config.etf_list}
    code_stop_loss_profiles = {e.symbol: e.stop_loss_profile for e in config.etf_list}
    code_volatility_groups = {e.symbol: e.volatility_group for e in config.etf_list}

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())
    if start is None:
        start = end - timedelta(days=config.lookback_days)

    median_atr_by_code = {
        code: _median_atr_pct(code, start, end)
        for code in codes
    }
    available_atr = [v for v in median_atr_by_code.values() if v is not None]
    atr_threshold = median(available_atr) if available_atr else None
    segments = build_market_volatility_segments(
        etf_items=config.etf_list,
        codes=codes,
        median_atr_by_code=median_atr_by_code,
        atr_threshold=atr_threshold,
    )

    experiments, baseline_name = get_ablation_experiments("stop-loss-rules")
    bt = PortfolioBacktest(
        calendar=calendar,
        initial_capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        cooldown_days=config.strategy_params.get("cooldown_days", 5),
        market_regime_params=config.market_regime_params,
        code_regime_groups=code_regime_groups,
        code_stop_loss_profiles=code_stop_loss_profiles,
        code_volatility_groups=code_volatility_groups,
    )

    segment_results = []
    for segment in segments:
        segment_codes = [item["symbol"] for item in segment["etfs"]]
        result = bt.run_experiments(
            codes=segment_codes,
            start=start,
            end=end,
            experiments=experiments,
        )
        result["meta"]["matrix"] = "stop-loss-rules"
        result["meta"]["baseline_name"] = baseline_name
        segment_results.append({
            **segment,
            "result": result,
            "best_name": _best_version_name(result),
        })

    return {
        "meta": {
            "start": str(start),
            "end": str(end),
            "codes": codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "stop-loss-by-segment",
            "atr_threshold": atr_threshold,
            "baseline_name": baseline_name,
        },
        "segments": segment_results,
    }


def build_market_volatility_segments(
    etf_items: list,
    codes: list[str],
    median_atr_by_code: dict[str, float | None],
    atr_threshold: float | None,
) -> list[dict[str, Any]]:
    """Build market x volatility segment records from ETF metadata."""

    item_by_symbol = {item.symbol: item for item in etf_items}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for code in codes:
        item = item_by_symbol.get(code)
        if item is None:
            continue
        market = getattr(item, "regime_group", None) or getattr(item, "market", None) or "UNKNOWN"
        median_atr = median_atr_by_code.get(code)
        vol_group = _volatility_group(median_atr, atr_threshold)
        key = (market, vol_group)
        grouped.setdefault(key, []).append({
            "symbol": code,
            "name": getattr(item, "name", code),
            "market": market,
            "median_atr_pct": median_atr,
        })

    segments = []
    for (market, vol_group), etfs in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        segments.append({
            "name": f"{market}_{vol_group}",
            "market": market,
            "vol_group": vol_group,
            "sample_warning": len(etfs) < 3,
            "etfs": sorted(etfs, key=lambda x: x["symbol"]),
        })
    return segments


def _build_config_segments(etf_items: list, selected_codes: set[str]) -> list[dict[str, Any]]:
    """Build fixed config-based validation segments."""

    items = [
        item for item in etf_items
        if item.symbol in selected_codes
    ]

    def item_record(item) -> dict[str, Any]:
        return {
            "symbol": item.symbol,
            "name": item.name,
            "market": item.regime_group,
            "volatility_group": item.volatility_group,
        }

    segment_specs = [
        ("全池", "全部 ETF", lambda item: True),
        ("A股高波动", "A股 high_vol", lambda item: item.regime_group == "A股" and item.volatility_group == "high_vol"),
        ("A股低波动", "A股 low_vol", lambda item: item.regime_group == "A股" and item.volatility_group == "low_vol"),
        ("港股", "港股 ETF", lambda item: item.regime_group == "港股"),
        ("美股", "美股 ETF", lambda item: item.regime_group == "美股"),
    ]

    segments = []
    for name, label, predicate in segment_specs:
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


def format_segmented_stop_loss_report(result: dict[str, Any]) -> str:
    """Format market x volatility stop-loss ablation results."""

    lines: list[str] = []
    meta = result["meta"]
    segments = result.get("segments", [])
    atr_threshold = meta.get("atr_threshold")

    lines.append("=" * 112)
    lines.append("  分市场/分波动 ETF 止损消融实验报告")
    lines.append("=" * 112)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  回测区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append(f"  波动分界: median_atr_pct = {_fmt_pct_value(atr_threshold)}")
    lines.append("  固定策略: 70/15/15阶梯建仓加仓 + 90自然日最大持有 + 当前门控")
    lines.append("  最优判定: Calmar 最高")
    lines.append("")

    if not segments:
        lines.append("  无可用分组结果。")
        return "\n".join(lines)

    lines.append("  分组最优汇总")
    headers = ["分组", "ETF数", "样本", "最优止损", "年化", "回撤", "Calmar", "胜率", "PF", "止损", "90日"]
    cols = [18, 6, 8, 12, 9, 9, 8, 9, 8, 6, 6]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for segment in segments:
        best = _segment_best_item(segment)
        if best is None:
            continue
        summary = best["summary"]
        stats = best.get("stats", {})
        lines.append(
            f"  {segment['name'][:18]:18s}"
            f" {len(segment['etfs']):>6d}"
            f" {_sample_label(segment):>8s}"
            f" {_version_label(best)[:12]:12s}"
            f" {summary.get('annual_return', 'N/A'):>9s}"
            f" {summary.get('max_drawdown', 'N/A'):>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {summary.get('win_rate', 'N/A'):>9s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {str(stats.get('stop_loss_triggered', 0)):>6s}"
            f" {str(stats.get('max_holding_exit', 0)):>6s}"
        )

    for segment in segments:
        lines.append("")
        lines.append(
            f"  [{segment['name']}] ETF={len(segment['etfs'])} "
            f"样本={_sample_label(segment)} "
            f"列表={_segment_etf_list(segment)}"
        )
        headers = ["策略", "年化", "回撤", "Calmar", "胜率", "PF", "交易", "止损", "90日", "标记"]
        cols = [12, 9, 9, 8, 9, 8, 6, 6, 6, 6]
        lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
        lines.append("  " + "  ".join("-" * c for c in cols))
        best_name = segment.get("best_name")
        versions = segment["result"].get("versions", {})
        for name, item in versions.items():
            summary = item["summary"]
            stats = item.get("stats", {})
            mark = "BEST" if name == best_name else ""
            lines.append(
                f"  {_version_label(item)[:12]:12s}"
                f" {summary.get('annual_return', 'N/A'):>9s}"
                f" {summary.get('max_drawdown', 'N/A'):>9s}"
                f" {summary.get('calmar', 'N/A'):>8s}"
                f" {summary.get('win_rate', 'N/A'):>9s}"
                f" {summary.get('profit_factor', 'N/A'):>8s}"
                f" {summary.get('total_trades', 'N/A'):>6s}"
                f" {str(stats.get('stop_loss_triggered', 0)):>6s}"
                f" {str(stats.get('max_holding_exit', 0)):>6s}"
                f" {mark:>6s}"
            )

    lines.append("")
    lines.append("  说明:")
    lines.append("  - 低/高波动按回测区间内每只 ETF 的 median_atr_pct 相对全池中位数划分。")
    lines.append("  - ETF 数量小于 3 的分组标记为样本不足，只作观察，不作为生产结论。")
    return "\n".join(lines)


def format_candidate_comparison_report(result: dict[str, Any]) -> str:
    """Format the two-window production candidate comparison report."""

    lines: list[str] = []
    meta = result["meta"]
    baseline_name = meta.get("baseline_name", "baseline_v2_3_gate_lite_regime")

    lines.append("=" * 118)
    lines.append("  候选策略对比实验报告")
    lines.append("=" * 118)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  对照组: 当前 baseline-v2.3 gate-lite + regime_group")
    lines.append("  实验组A: baseline + 70/15/15阶梯建仓加仓 + 90日最大持有 + 固定-8%止损")
    lines.append("  实验组B: 实验组A + settings.yaml 分市场/分波动止损 profile")
    lines.append("")

    for window in result.get("windows", []):
        _append_candidate_window(lines, window, baseline_name)

    lines.append("  说明:")
    lines.append("  - A/B 仍受单 ETF 30% 仓位上限约束；70/15/15 是单 ETF 目标预算内的建仓/加仓拆分。")
    lines.append("  - 分段止损 profile 来自 settings.yaml；样本不足的港股/美股 ETF 保持 fixed_8。")
    lines.append("  - Δ回撤为相对对照组的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def format_reentry_rules_report(result: dict[str, Any]) -> str:
    """Format stop-loss reentry rule ablation results."""

    lines: list[str] = []
    meta = result["meta"]
    baseline_name = meta.get("baseline_name", "baseline_v2_4_segment_stop")

    lines.append("=" * 128)
    lines.append("  止损后再入场规则消融实验报告")
    lines.append("=" * 128)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  基线: baseline-v2.4 = 70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有")
    lines.append("  说明: 仅过滤止损退出后的下一次建仓；普通首次建仓和非止损退出后的再建仓不受影响。")
    lines.append("")

    for window in result.get("windows", []):
        _append_reentry_window(lines, window, baseline_name)

    lines.append("  指标说明:")
    lines.append("  - 再试: 止损后再次出现建仓建议的次数；通过/拦截: 被再入场规则允许或过滤的次数。")
    lines.append("  - 再成: 实际完成的再入场建仓次数；再胜率/再均收/二停率仅统计已平仓的再入场交易。")
    lines.append("  - Δ回撤为相对 baseline-v2.4 的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def format_trend_reentry_segments_report(result: dict[str, Any]) -> str:
    """Format trend-repair reentry validation by segment."""

    lines: list[str] = []
    meta = result["meta"]
    baseline_name = meta.get("baseline_name", "baseline_v2_4_segment_stop")
    candidate_name = "candidate_v2_5_trend_reentry"

    lines.append("=" * 132)
    lines.append("  趋势修复再入场分组验证报告")
    lines.append("=" * 132)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  对照组: baseline-v2.4 = 70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有")
    lines.append("  实验组: 趋势修复 = baseline-v2.4 + 止损后 close>MA20、MA20>MA60、ADX>=20、MACD为正")
    lines.append("")

    for window in result.get("windows", []):
        lines.append(f"  区间: {window['label']} ({window['start']} ~ {window['end']})")
        headers = [
            "分组", "ETF", "样本", "基线年化", "趋势年化", "Δ年化",
            "基线回撤", "趋势回撤", "Δ回撤", "基线Cal", "趋势Cal",
            "基线胜率", "趋势胜率", "再成", "再胜率", "二停率", "判断",
        ]
        cols = [10, 4, 8, 9, 9, 8, 9, 9, 8, 8, 8, 9, 9, 5, 8, 8, 12]
        lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
        lines.append("  " + "  ".join("-" * c for c in cols))

        for segment in window.get("segments", []):
            versions = segment["result"].get("versions", {})
            baseline = versions.get(baseline_name)
            candidate = versions.get(candidate_name)
            if baseline is None or candidate is None:
                continue
            base_summary = baseline["summary"]
            cand_summary = candidate["summary"]
            cand_stats = candidate.get("stats", {})
            judgement = _trend_reentry_judgement(base_summary, cand_summary, segment)
            lines.append(
                f"  {segment['name'][:10]:10s}"
                f" {len(segment['codes']):>4d}"
                f" {_sample_label(segment):>8s}"
                f" {_metric(base_summary, 'annual_return'):>9s}"
                f" {_metric(cand_summary, 'annual_return'):>9s}"
                f" {_delta_pct(cand_summary, base_summary, 'annual_return', lower_is_better=False):>8s}"
                f" {_metric(base_summary, 'max_drawdown'):>9s}"
                f" {_metric(cand_summary, 'max_drawdown'):>9s}"
                f" {_delta_pct(cand_summary, base_summary, 'max_drawdown', lower_is_better=True):>8s}"
                f" {base_summary.get('calmar', 'N/A'):>8s}"
                f" {cand_summary.get('calmar', 'N/A'):>8s}"
                f" {_metric(base_summary, 'win_rate'):>9s}"
                f" {_metric(cand_summary, 'win_rate'):>9s}"
                f" {str(cand_stats.get('reentry_executed', 0)):>5s}"
                f" {_reentry_win_rate(cand_stats):>8s}"
                f" {_reentry_second_stop_rate(cand_stats):>8s}"
                f" {judgement[:12]:12s}"
            )
        lines.append("")

    lines.append("  分组 ETF:")
    for segment in result.get("windows", [{}])[0].get("segments", []):
        lines.append(f"  - {segment['name']}: {', '.join(segment['codes'])}")
    lines.append("")
    lines.append("  判断口径:")
    lines.append("  - 全池和 A股高/低波动为主要采纳依据；港股/美股样本不足，只观察副作用。")
    lines.append("  - 采纳优先看长区间回撤相对下降 >=5%、Calmar 提升，且年化下降不超过 1pct。")
    return "\n".join(lines)


def format_high_vol_reentry_cooldown_report(result: dict[str, Any]) -> str:
    """Format high-volatility cooldown reentry experiments."""

    lines: list[str] = []
    meta = result["meta"]
    baseline_name = meta.get("baseline_name", "baseline_v2_4_segment_stop")

    lines.append("=" * 136)
    lines.append("  高波动 ETF 止损后再入场冷静期实验报告")
    lines.append("=" * 136)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  基线: baseline-v2.4 = 70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有")
    lines.append("  实验: 仅对指定波动/市场 ETF 的止损后再入场设置交易日冷静期，期满后按普通建仓处理。")
    lines.append("")

    for window in result.get("windows", []):
        lines.append(f"  区间: {window['label']} ({window['start']} ~ {window['end']})")
        for segment in window.get("segments", []):
            _append_high_vol_cooldown_segment(lines, segment, baseline_name)
        lines.append("")

    lines.append("  分组 ETF:")
    for segment in result.get("windows", [{}])[0].get("segments", []):
        lines.append(f"  - {segment['name']}: {', '.join(segment['codes'])}")
    lines.append("")
    lines.append("  说明:")
    lines.append("  - 高波10T/15T/20T/30T 作用于所有 high_vol ETF；A高波20T 只作用于 A股 high_vol。")
    lines.append("  - 低波20T 是反证组，只作用于 low_vol ETF。")
    lines.append("  - Δ回撤为相对 baseline-v2.4 的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def format_high_vol_reentry_stop_price_report(result: dict[str, Any]) -> str:
    """Format high-volatility stop-price reclaim reentry experiments."""

    lines: list[str] = []
    meta = result["meta"]
    baseline_name = meta.get("baseline_name", "baseline_v2_4_segment_stop")

    lines.append("=" * 136)
    lines.append("  高波动 ETF 止损价再入场约束实验报告")
    lines.append("=" * 136)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  基线: baseline-v2.4 = 70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有")
    lines.append("  实验: 止损后再次建仓要求重新入场价高于上一次止损卖出价。")
    lines.append("")

    for window in result.get("windows", []):
        lines.append(f"  区间: {window['label']} ({window['start']} ~ {window['end']})")
        for segment in window.get("segments", []):
            _append_high_vol_cooldown_segment(lines, segment, baseline_name)
        lines.append("")

    lines.append("  分组 ETF:")
    for segment in result.get("windows", [{}])[0].get("segments", []):
        lines.append(f"  - {segment['name']}: {', '.join(segment['codes'])}")
    lines.append("")
    lines.append("  说明:")
    lines.append("  - 高波止损价作用于所有 high_vol ETF；A高波止损价只作用于 A股 high_vol。")
    lines.append("  - 低波止损价是反证组，只作用于 low_vol ETF。")
    lines.append("  - Δ回撤为相对 baseline-v2.4 的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def _append_high_vol_cooldown_segment(
    lines: list[str],
    segment: dict[str, Any],
    baseline_name: str,
) -> None:
    versions = segment["result"].get("versions", {})
    baseline = versions.get(baseline_name)
    if baseline is None:
        return
    baseline_summary = baseline["summary"]

    lines.append(f"  [{segment['name']}] ETF={len(segment['codes'])} 样本={_sample_label(segment)}")
    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "Sharpe", "胜率", "PF",
        "交易", "再试", "通过", "拦截", "再成", "再胜率", "再均收", "二停率",
    ]
    cols = [14, 9, 9, 9, 9, 8, 8, 9, 8, 6, 6, 6, 6, 6, 8, 8, 8]
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
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {str(stats.get('reentry_attempts', 0)):>6s}"
            f" {str(stats.get('reentry_allowed', 0)):>6s}"
            f" {str(stats.get('reentry_blocked', 0)):>6s}"
            f" {str(stats.get('reentry_executed', 0)):>6s}"
            f" {_reentry_win_rate(stats):>8s}"
            f" {_reentry_avg_return(stats):>8s}"
            f" {_reentry_second_stop_rate(stats):>8s}"
        )
    lines.append("")


def _trend_reentry_judgement(
    baseline_summary: dict[str, Any],
    candidate_summary: dict[str, Any],
    segment: dict[str, Any],
) -> str:
    annual = _parse_percent(candidate_summary.get("annual_return"))
    base_annual = _parse_percent(baseline_summary.get("annual_return"))
    drawdown = _parse_percent(candidate_summary.get("max_drawdown"))
    base_drawdown = _parse_percent(baseline_summary.get("max_drawdown"))
    calmar = _parse_number(candidate_summary.get("calmar"))
    base_calmar = _parse_number(baseline_summary.get("calmar"))

    if segment.get("sample_warning"):
        return "观察"
    if None in (annual, base_annual, drawdown, base_drawdown, calmar, base_calmar):
        return "待判断"

    annual_delta_pct = annual - base_annual
    drawdown_improve_rel = (base_drawdown - drawdown) / base_drawdown if base_drawdown else 0.0
    if drawdown_improve_rel >= 0.05 and calmar > base_calmar and annual_delta_pct >= -0.01:
        return "推荐"
    if drawdown_improve_rel > 0 and calmar >= base_calmar and annual_delta_pct >= -0.01:
        return "可观察"
    if drawdown > base_drawdown or annual_delta_pct < -0.01:
        return "不推荐"
    return "中性"


def _append_reentry_window(
    lines: list[str],
    result: dict[str, Any],
    baseline_name: str,
) -> None:
    meta = result["meta"]
    versions = result.get("versions", {})
    lines.append(f"  区间: {meta['window']} ({meta['start']} ~ {meta['end']})")
    if not versions:
        lines.append("  无可用实验结果：请确认 signals 已完成重算。")
        lines.append("")
        return

    baseline = versions.get(baseline_name) or next(iter(versions.values()))
    baseline_summary = baseline["summary"]

    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "Sharpe", "胜率", "PF",
        "交易", "再试", "通过", "拦截", "再成", "再胜率", "再均收", "二停率",
    ]
    cols = [14, 9, 9, 9, 9, 8, 8, 9, 8, 6, 6, 6, 6, 6, 8, 8, 8]
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
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {str(stats.get('reentry_attempts', 0)):>6s}"
            f" {str(stats.get('reentry_allowed', 0)):>6s}"
            f" {str(stats.get('reentry_blocked', 0)):>6s}"
            f" {str(stats.get('reentry_executed', 0)):>6s}"
            f" {_reentry_win_rate(stats):>8s}"
            f" {_reentry_avg_return(stats):>8s}"
            f" {_reentry_second_stop_rate(stats):>8s}"
        )
    lines.append("")


def _append_candidate_window(
    lines: list[str],
    result: dict[str, Any],
    baseline_name: str,
) -> None:
    meta = result["meta"]
    versions = result.get("versions", {})
    lines.append(f"  区间: {meta['window']} ({meta['start']} ~ {meta['end']})")
    if not versions:
        lines.append("  无可用实验结果：请确认 signals 已完成重算。")
        lines.append("")
        return

    baseline = versions.get(baseline_name) or next(iter(versions.values()))
    baseline_summary = baseline["summary"]

    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "Calmar", "Sharpe",
        "胜率", "Δ胜率", "PF", "交易", "均持", "最大持有", "加仓", "止损", "90日",
    ]
    cols = [18, 9, 9, 9, 9, 8, 8, 9, 9, 8, 6, 7, 8, 6, 6, 6]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for name, item in versions.items():
        summary = item["summary"]
        stats = item.get("stats", {})
        exp = item.get("experiment", {})
        holding = _holding_stats(item.get("trades", []))
        label = exp.get("label") or name
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
            f" {holding['avg_holding_days']:>7s}"
            f" {holding['max_holding_days']:>8s}"
            f" {str(stats.get('add_executed', 0)):>6s}"
            f" {str(stats.get('stop_loss_triggered', 0)):>6s}"
            f" {str(stats.get('max_holding_exit', 0)):>6s}"
        )
    lines.append("")


def format_ablation_report(result: dict[str, Any], baseline_name: str | None = None) -> str:
    """Format ablation results as a CLI-friendly comparison table."""

    lines: list[str] = []
    meta = result["meta"]
    versions = result.get("versions", {})
    baseline_name = baseline_name or meta.get("baseline_name") or "baseline_full_gate"

    lines.append("=" * 96)
    lines.append("  因子消融实验报告")
    lines.append("=" * 96)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  回测区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append(f"  实验集: {meta.get('matrix', 'default')}")
    lines.append("")

    if not versions:
        lines.append("  无可用实验结果：请确认 signals 已完成重算。")
        return "\n".join(lines)

    baseline = versions.get(baseline_name) or next(iter(versions.values()))
    baseline_summary = baseline["summary"]

    headers = [
        "实验", "年化", "Δ年化", "回撤", "Δ回撤", "胜率", "Δ胜率",
        "PF", "交易", "均持", "最大持有", "加仓", "均加份额", "加仓过滤",
        "止损", "90日退出", "溢价拦截", "市场拦截",
    ]
    cols = [18, 9, 9, 9, 9, 9, 9, 7, 6, 7, 8, 6, 8, 8, 6, 8, 10, 10]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))

    for name, item in versions.items():
        summary = item["summary"]
        stats = item.get("stats", {})
        exp = item.get("experiment", {})
        holding = _holding_stats(item.get("trades", []))
        label = exp.get("label") or name
        lines.append(
            f"  {label[:18]:18s}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'annual_return', lower_is_better=False):>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'max_drawdown', lower_is_better=True):>9s}"
            f" {_metric(summary, 'win_rate'):>9s}"
            f" {_delta_pct(summary, baseline_summary, 'win_rate', lower_is_better=False):>9s}"
            f" {summary.get('profit_factor', 'N/A'):>7s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {holding['avg_holding_days']:>7s}"
            f" {holding['max_holding_days']:>8s}"
            f" {str(stats.get('add_executed', 0)):>6s}"
            f" {_avg_add_shares(stats):>8s}"
            f" {str(stats.get('add_rule_blocked', 0)):>8s}"
            f" {str(stats.get('stop_loss_triggered', 0)):>6s}"
            f" {str(stats.get('max_holding_exit', 0)):>8s}"
            f" {str(stats.get('premium_blocked', 0)):>10s}"
            f" {str(stats.get('market_blocked', 0)):>10s}"
        )

    lines.append("")
    lines.append("  说明:")
    lines.append("  - 第一版消融只切换回测层因子开关，不重算不同交易周期参数的策略信号。")
    if meta.get("matrix") == "preferred-cycle":
        lines.append("  - preferred-cycle 实验集统一增加最长 90 个自然日持有约束。")
    if meta.get("matrix") == "add-rules":
        lines.append("  - add-rules 实验集统一增加最长 90 个自然日持有约束，并只比较加仓执行规则。")
    if meta.get("matrix") == "entry-add-budget":
        lines.append("  - entry-add-budget 实验集统一增加最长 90 个自然日持有约束，并比较建仓/加仓资金分配。")
    if meta.get("matrix") == "stop-loss-rules":
        lines.append("  - stop-loss-rules 实验集固定 70/15/15阶梯建仓加仓，并只比较止损规则。")
    if meta.get("matrix") == "candidate-comparison":
        lines.append("  - candidate-comparison 实验集比较当前基线、70/15/15 和分段止损候选方案。")
    lines.append("  - Δ回撤为相对 baseline 的改善值，正数表示回撤下降。")
    return "\n".join(lines)


def _median_atr_pct(code: str, start: date, end: date) -> float | None:
    indicators = indicators_repo.find_by_code_between(code, start, end)
    values = [
        float(ind.data["atr_pct"])
        for ind in indicators
        if ind.data.get("atr_pct") is not None
    ]
    return median(values) if values else None


def _volatility_group(median_atr_pct: float | None, threshold: float | None) -> str:
    if median_atr_pct is None or threshold is None:
        return "unknown_vol"
    if median_atr_pct < threshold:
        return "low_vol"
    return "high_vol"


def _best_version_name(result: dict[str, Any]) -> str | None:
    versions = result.get("versions", {})
    best_name = None
    best_key = None
    for name, item in versions.items():
        summary = item.get("summary", {})
        calmar = _parse_number(summary.get("calmar"))
        annual = _parse_percent(summary.get("annual_return"))
        drawdown = _parse_percent(summary.get("max_drawdown"))
        if calmar is None:
            continue
        key = (calmar, annual if annual is not None else -999, -(drawdown or 999))
        if best_key is None or key > best_key:
            best_key = key
            best_name = name
    return best_name


def _segment_best_item(segment: dict[str, Any]) -> dict[str, Any] | None:
    best_name = segment.get("best_name")
    if best_name is None:
        return None
    return segment["result"].get("versions", {}).get(best_name)


def _version_label(item: dict[str, Any]) -> str:
    exp = item.get("experiment", {})
    return exp.get("label") or ""


def _sample_label(segment: dict[str, Any]) -> str:
    return "样本不足" if segment.get("sample_warning") else "可参考"


def _segment_etf_list(segment: dict[str, Any]) -> str:
    parts = []
    for item in segment.get("etfs", []):
        atr = _fmt_pct_value(item.get("median_atr_pct"))
        parts.append(f"{item['symbol']}({atr})")
    return ", ".join(parts)


def _fmt_pct_value(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.2%}"


def _holding_stats(trades: list) -> dict[str, str]:
    closed = pair_closed_trades(trades)
    if not closed:
        return {"avg_holding_days": "N/A", "max_holding_days": "N/A"}
    days = sorted(t["holding_days"] for t in closed)
    avg_days = sum(days) / len(days)
    return {
        "avg_holding_days": f"{avg_days:.1f}",
        "max_holding_days": str(max(days)),
    }


def _metric(summary: dict[str, Any], key: str) -> str:
    return str(summary.get(key, "N/A"))


def _avg_add_shares(stats: dict[str, Any]) -> str:
    count = stats.get("add_executed", 0) or 0
    if count <= 0:
        return "N/A"
    total = stats.get("add_shares_total", 0.0) or 0.0
    return f"{total / count:.0f}"


def _reentry_win_rate(stats: dict[str, Any]) -> str:
    closed = stats.get("reentry_closed", 0) or 0
    if closed <= 0:
        return "N/A"
    return f"{(stats.get('reentry_wins', 0) or 0) / closed:.2%}"


def _reentry_avg_return(stats: dict[str, Any]) -> str:
    closed = stats.get("reentry_closed", 0) or 0
    if closed <= 0:
        return "N/A"
    return f"{(stats.get('reentry_pnl_pct_total', 0.0) or 0.0) / closed:.2%}"


def _reentry_second_stop_rate(stats: dict[str, Any]) -> str:
    closed = stats.get("reentry_closed", 0) or 0
    if closed <= 0:
        return "N/A"
    return f"{(stats.get('reentry_stop_loss_exit', 0) or 0) / closed:.2%}"


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
