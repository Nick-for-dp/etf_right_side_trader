"""Stop-loss event attribution for the current production baseline."""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

from src.backtest.ablation_config import (
    HIGH_VOL_QUALITY_BUDGET_TIER,
    SIGNAL_PROFILE_HIGH_VOL_BALANCED,
    production_v2_4_experiment,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.backtest.portfolio_metrics import pair_closed_trades
from src.database import indicators_repo, market_regime_repo, quote_repo
from src.service.calendar_service import TradingCalendarService
from src.service.market_regime_service import build_per_code_market_regime

PRODUCTION_NAME = "v2_5_limited"
_WINDOWS = (5, 10, 20, 60)


def run_stop_loss_attribution_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run v2.5 limited and attribute every stop-loss exit event."""

    from src.config import load_config

    config = load_config()
    selected_codes = codes or [item.symbol for item in config.etf_list]
    selected_set = set(selected_codes)
    code_meta = {
        item.symbol: {
            "name": item.name,
            "market": item.market,
            "regime_group": item.regime_group,
            "volatility_group": item.volatility_group,
            "stop_loss_profile": item.stop_loss_profile,
            "sector": item.sector,
            "theme": item.theme,
            "category": item.category,
        }
        for item in config.etf_list
        if item.symbol in selected_set
    }
    code_regime_groups = {
        code: code_meta.get(code, {}).get("regime_group", "A股")
        for code in selected_codes
    }

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())
    if start is None:
        start = date(2016, 1, 1)

    experiments = [_production_v25_experiment()]
    result = run_ablation_backtest(
        codes=selected_codes,
        start=start,
        end=end,
        capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        experiments=experiments,
        matrix="stop-loss-attribution",
    )
    version = result.get("versions", {}).get(PRODUCTION_NAME)
    if version is None:
        raise RuntimeError(f"missing backtest version: {PRODUCTION_NAME}")

    trading_days = calendar.get_trading_days_in_range(start, end)
    price_map = _load_price_map(selected_codes, start, end)
    indicator_map = _load_indicator_map(selected_codes, start, end)
    regime_by_day = _load_per_code_regime_map(
        trading_days,
        code_regime_groups,
        config.market_regime_params,
    )
    events = build_stop_loss_events(
        version,
        trading_days=trading_days,
        price_map=price_map,
        indicator_map=indicator_map,
        regime_by_day=regime_by_day,
        code_meta=code_meta,
    )
    closed_trades = pair_closed_trades(version.get("trades", []))

    return {
        "meta": {
            "start": str(start),
            "end": str(end),
            "codes": selected_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "version": PRODUCTION_NAME,
            "label": "v2.5 limited",
        },
        "summary": _summary(version, closed_trades, events),
        "by_etf": _summarize_by(events, "code", code_meta=code_meta),
        "by_market_state": _summarize_by(events, "market_state"),
        "by_volatility_group": _summarize_by(events, "volatility_group"),
        "by_stop_loss_profile": _summarize_by(events, "stop_loss_profile"),
        "by_atr_bucket": _summarize_by(events, "atr_bucket"),
        "events": events,
    }


def build_stop_loss_events(
    version: dict[str, Any],
    *,
    trading_days: list[str],
    price_map: dict[str, dict[str, float]],
    indicator_map: dict[str, dict[str, dict]],
    regime_by_day: dict[str, dict[str, dict]],
    code_meta: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Build event-level stop-loss attribution rows from a backtest version."""

    closed = pair_closed_trades(version.get("trades", []))
    closed_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in closed:
        closed_by_code[item["code"]].append(item)
    for items in closed_by_code.values():
        items.sort(key=lambda row: (row["entry_date"], row["exit_date"]))

    day_index = {day: idx for idx, day in enumerate(trading_days)}
    events: list[dict[str, Any]] = []
    for item in closed:
        if item.get("exit_signal_source") != "stop_loss":
            continue
        code = item["code"]
        exit_day = str(item["exit_date"])
        exit_idx = day_index.get(exit_day)
        trigger_idx = exit_idx - 1 if exit_idx is not None and exit_idx > 0 else exit_idx
        trigger_day = trading_days[trigger_idx] if trigger_idx is not None else exit_day
        indicator = indicator_map.get(code, {}).get(trigger_day, {})
        meta = code_meta.get(code, {})
        market_state = (
            regime_by_day.get(trigger_day, {})
            .get(code, {})
            .get("state", "UNKNOWN")
        )
        event = {
            "code": code,
            "name": meta.get("name", code),
            "entry_date": item["entry_date"],
            "trigger_date": date.fromisoformat(trigger_day),
            "exit_date": item["exit_date"],
            "entry_price": item["entry_price"],
            "trigger_price": price_map.get(code, {}).get(trigger_day),
            "exit_price": item["exit_price"],
            "shares": item["shares"],
            "exit_value": item["exit_price"] * item["shares"],
            "pnl_cash": item["pnl_cash"],
            "pnl_pct": item["pnl_pct"],
            "holding_days": item["holding_days"],
            "exit_reason": item.get("exit_reason"),
            "threshold_pct": _parse_threshold(item.get("exit_reason")),
            "market": meta.get("market", "unknown"),
            "market_state": market_state,
            "regime_group": meta.get("regime_group", "unknown"),
            "volatility_group": meta.get("volatility_group", "unknown_vol"),
            "stop_loss_profile": meta.get("stop_loss_profile", "unknown"),
            "sector": meta.get("sector", ""),
            "theme": meta.get("theme", ""),
            "category": meta.get("category", ""),
            "atr_pct": _to_float(indicator.get("atr_pct")),
            "atr_bucket": _atr_bucket(_to_float(indicator.get("atr_pct"))),
            "adx14": _to_float(indicator.get("adx14")),
            "rsi": _to_float(indicator.get("rsi")),
            "ma20": _to_float(indicator.get("ma20")),
            "ma60": _to_float(indicator.get("ma60")),
        }
        if event["trigger_price"] and event["exit_price"]:
            event["execution_gap_pct"] = (
                event["exit_price"] - event["trigger_price"]
            ) / event["trigger_price"]
        else:
            event["execution_gap_pct"] = None

        for window in _WINDOWS:
            future_ret = _future_return(
                code=code,
                exit_idx=exit_idx,
                exit_price=item["exit_price"],
                window=window,
                trading_days=trading_days,
                price_map=price_map,
            )
            event[f"ret_{window}d"] = future_ret
            event[f"move_cash_{window}d"] = (
                item["exit_price"] * item["shares"] * future_ret
                if future_ret is not None else None
            )
        events.append(event)

    for event in events:
        next_trade = _next_closed_trade(closed_by_code.get(event["code"], []), event["exit_date"])
        event["has_next_trade"] = next_trade is not None
        event["secondary_stop_loss"] = (
            next_trade is not None
            and next_trade.get("exit_signal_source") == "stop_loss"
        )
        event["next_trade_pnl_pct"] = next_trade.get("pnl_pct") if next_trade else None
        event["next_exit_source"] = next_trade.get("exit_signal_source") if next_trade else None

    return sorted(events, key=lambda row: (row["exit_date"], row["code"]))


def format_stop_loss_attribution_report(result: dict[str, Any]) -> str:
    """Format stop-loss attribution into a terminal-friendly report."""

    meta = result["meta"]
    summary = result["summary"]
    lines: list[str] = []
    lines.append("=" * 140)
    lines.append("  止损事件级归因报告")
    lines.append("=" * 140)
    lines.append(f"  版本: {meta['label']}")
    lines.append(f"  区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("")
    lines.append("  总览")
    lines.append(
        "  "
        f"闭合交易 {summary['closed_trades']} 笔，"
        f"止损 {summary['stop_events']} 次，"
        f"止损总损益 {_fmt_money(summary['stop_pnl_cash'])}，"
        f"占亏损金额 {_fmt_pct(summary['stop_loss_amount_share'])}。"
    )
    lines.append(
        "  "
        f"高波止损 {summary['high_vol_stop_events']} 次，"
        f"高波止损损益 {_fmt_money(summary['high_vol_stop_pnl_cash'])}，"
        f"二次止损率 {_fmt_pct(summary['secondary_stop_rate'])}。"
    )
    lines.append(
        "  "
        f"止损后20日均值 {_fmt_pct(summary.get('ret_20d_avg'), signed=True)}，"
        f"上涨占比 {_fmt_pct(summary.get('ret_20d_pos_rate'))}，"
        f"静态价格变动 {_fmt_money(summary.get('move_cash_20d_total'), signed=True)}。"
    )
    lines.append(
        "  "
        f"止损后60日均值 {_fmt_pct(summary.get('ret_60d_avg'), signed=True)}，"
        f"60日继续下跌占比 {_fmt_pct(summary.get('ret_60d_neg_rate'))}。"
    )
    lines.append("")

    _append_group_table(
        lines,
        "按 ETF 拆解（按止损总损益从差到好）",
        _top_rows(result["by_etf"], key="pnl_cash_total", reverse=False, limit=14),
        label_key="label",
    )
    high_vol_rows = [
        row for row in result["by_etf"]
        if row.get("volatility_group") == "high_vol"
    ]
    _append_group_table(
        lines,
        "高波 ETF 止损损益来源",
        sorted(high_vol_rows, key=lambda row: row["pnl_cash_total"])[:14],
        label_key="label",
    )
    _append_group_table(
        lines,
        "按市场状态拆解",
        sorted(result["by_market_state"], key=lambda row: row["count"], reverse=True),
    )
    _append_group_table(
        lines,
        "按波动组拆解",
        sorted(result["by_volatility_group"], key=lambda row: row["count"], reverse=True),
    )
    _append_group_table(
        lines,
        "按止损 Profile 拆解",
        sorted(result["by_stop_loss_profile"], key=lambda row: row["count"], reverse=True),
    )
    _append_group_table(
        lines,
        "按 ATR 桶拆解",
        sorted(result["by_atr_bucket"], key=_atr_bucket_sort_key),
    )
    lines.append(f"  初步判断: {_diagnosis(result)}")
    lines.append("")
    lines.append("  说明:")
    lines.append("  - 止损触发日使用卖出成交日前一交易日，避免使用成交日之后数据。")
    lines.append("  - 止损后收益按实际卖出成交价到后续 5/10/20/60 个交易日收盘价计算。")
    lines.append("  - 静态价格变动是假设卖出份额继续持有到窗口日的价格变化，不等同于真实可执行收益。")
    lines.append("  - 二次止损率分母为止损后存在下一笔已平仓交易的样本。")
    return "\n".join(lines)


def _production_v25_experiment():
    return production_v2_4_experiment(
        name=PRODUCTION_NAME,
        label="v2.5 limited",
        experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
        high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
        description=(
            "当前生产基线：high_vol 使用 high_vol_balanced，"
            "并按 score 质量分层目标预算；low_vol 保持 baseline-v2.4。"
        ),
    )


def _summary(
    version: dict[str, Any],
    closed_trades: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = dict(version.get("summary", {}))
    stop_pnl = sum(row["pnl_cash"] for row in events)
    total_loss = abs(sum(row["pnl_cash"] for row in closed_trades if row["pnl_cash"] < 0))
    high_vol = [row for row in events if row.get("volatility_group") == "high_vol"]
    event_summary = _summarize_events(events)
    summary.update(event_summary)
    summary.update({
        "closed_trades": len(closed_trades),
        "stop_events": len(events),
        "stop_pnl_cash": stop_pnl,
        "stop_loss_amount_share": abs(stop_pnl) / total_loss if total_loss > 0 else None,
        "high_vol_stop_events": len(high_vol),
        "high_vol_stop_pnl_cash": sum(row["pnl_cash"] for row in high_vol),
    })
    return summary


def _summarize_by(
    events: list[dict[str, Any]],
    key: str,
    *,
    code_meta: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in events:
        groups[str(row.get(key) or "UNKNOWN")].append(row)

    rows = []
    for value, items in groups.items():
        summary = _summarize_events(items)
        row = {"key": value, "label": value, **summary}
        if key == "code":
            meta = (code_meta or {}).get(value, {})
            row.update({
                "label": f"{value} {meta.get('name', '')}".strip(),
                "volatility_group": meta.get("volatility_group"),
                "regime_group": meta.get("regime_group"),
                "stop_loss_profile": meta.get("stop_loss_profile"),
            })
        rows.append(row)
    return rows


def _summarize_events(items: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(items)
    if count == 0:
        return {"count": 0}

    next_samples = [row for row in items if row.get("has_next_trade")]
    result: dict[str, Any] = {
        "count": count,
        "pnl_cash_total": sum(row["pnl_cash"] for row in items),
        "pnl_pct_avg": _avg(row["pnl_pct"] for row in items),
        "pnl_pct_median": _median(row["pnl_pct"] for row in items),
        "holding_days_avg": _avg(row["holding_days"] for row in items),
        "atr_pct_avg": _avg(row.get("atr_pct") for row in items),
        "execution_gap_avg": _avg(row.get("execution_gap_pct") for row in items),
        "secondary_stop_count": sum(1 for row in next_samples if row.get("secondary_stop_loss")),
        "secondary_sample_count": len(next_samples),
        "secondary_stop_rate": (
            sum(1 for row in next_samples if row.get("secondary_stop_loss")) / len(next_samples)
            if next_samples else None
        ),
    }
    for window in _WINDOWS:
        values = [row.get(f"ret_{window}d") for row in items if row.get(f"ret_{window}d") is not None]
        result[f"ret_{window}d_avg"] = _avg(values)
        result[f"ret_{window}d_median"] = _median(values)
        result[f"ret_{window}d_pos_rate"] = _ratio(values, lambda value: value > 0)
        result[f"ret_{window}d_neg_rate"] = _ratio(values, lambda value: value < 0)
        result[f"ret_{window}d_sample"] = len(values)
        move_values = [
            row.get(f"move_cash_{window}d")
            for row in items
            if row.get(f"move_cash_{window}d") is not None
        ]
        result[f"move_cash_{window}d_total"] = (
            sum(move_values) if move_values else None
        )
    return result


def _append_group_table(
    lines: list[str],
    title: str,
    rows: list[dict[str, Any]],
    *,
    label_key: str = "key",
) -> None:
    lines.append(f"  {title}")
    if not rows:
        lines.append("  无样本")
        lines.append("")
        return
    headers = ["分组", "次数", "总损益", "均损", "ATR均", "20日后", "20日涨", "20日价变", "60日后", "60日跌", "二次止损"]
    cols = [24, 6, 10, 8, 8, 9, 8, 10, 9, 8, 9]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        label = str(row.get(label_key, row.get("key", "")))[:24]
        lines.append(
            f"  {label:24s}"
            f" {row.get('count', 0):>6d}"
            f" {_fmt_money(row.get('pnl_cash_total')):>10s}"
            f" {_fmt_pct(row.get('pnl_pct_avg'), signed=True):>8s}"
            f" {_fmt_pct(row.get('atr_pct_avg')):>8s}"
            f" {_fmt_pct(row.get('ret_20d_avg'), signed=True):>9s}"
            f" {_fmt_pct(row.get('ret_20d_pos_rate')):>8s}"
            f" {_fmt_money(row.get('move_cash_20d_total'), signed=True):>10s}"
            f" {_fmt_pct(row.get('ret_60d_avg'), signed=True):>9s}"
            f" {_fmt_pct(row.get('ret_60d_neg_rate')):>8s}"
            f" {_fmt_pct(row.get('secondary_stop_rate')):>9s}"
        )
    lines.append("")


def _diagnosis(result: dict[str, Any]) -> str:
    high_vol_rows = [
        row for row in result.get("by_etf", [])
        if row.get("volatility_group") == "high_vol"
    ]
    if not high_vol_rows:
        return "高波止损样本不足，暂不能判断 ATR profile 是否需要调整。"
    high_vol_count = sum(row["count"] for row in high_vol_rows)
    high_vol_pnl = sum(row["pnl_cash_total"] for row in high_vol_rows)
    high_vol_20d = _weighted_avg(high_vol_rows, "ret_20d_avg", "ret_20d_sample")
    high_vol_20d_pos = _weighted_avg(high_vol_rows, "ret_20d_pos_rate", "ret_20d_sample")
    high_vol_move20 = sum(
        row.get("move_cash_20d_total") or 0.0
        for row in high_vol_rows
    )
    high_vol_60d = _weighted_avg(high_vol_rows, "ret_60d_avg", "ret_60d_sample")
    secondary = _weighted_avg(high_vol_rows, "secondary_stop_rate", "secondary_sample_count")
    if high_vol_count < 10:
        if high_vol_20d is not None and high_vol_20d > 0:
            return (
                "高波止损样本少于 10 次，但止损后 20 日平均反弹 "
                f"{_fmt_pct(high_vol_20d, signed=True)}、上涨占比 {_fmt_pct(high_vol_20d_pos)}、"
                f"静态价格变动 {_fmt_money(high_vol_move20, signed=True)}；"
                "不能认定止损影响小，应继续做误止损和再入场机会成本归因。"
            )
        return "高波止损样本少于 10 次，先继续累积样本，暂不下 ATR 调整结论。"
    if high_vol_60d is not None and high_vol_60d > 0.03 and (secondary is None or secondary < 0.35):
        return (
            "高波止损后 60 日平均反弹偏强且二次止损率不高，"
            "ATR profile 可能偏紧，应优先实验更宽 ATR 或分层止损。"
        )
    if high_vol_60d is not None and high_vol_60d < -0.03:
        return (
            "高波止损后 60 日仍明显走弱，止损整体有效；"
            "下一步更应优化再入场或组合暴露，而不是简单放宽 ATR。"
        )
    return (
        f"高波止损 {high_vol_count} 次，总损益 {_fmt_money(high_vol_pnl)}；"
        "当前证据不支持直接调整 ATR profile，建议先看损失集中的 ETF/市场状态。"
    )


def _load_price_map(codes: list[str], start: date, end: date) -> dict[str, dict[str, float]]:
    fetch_start = start - timedelta(days=120)
    result: dict[str, dict[str, float]] = {}
    for code in codes:
        quotes = quote_repo.find_by_code_in_range(code, fetch_start, end)
        result[code] = {
            str(item.date): float(item.close)
            for item in quotes
            if item.close is not None
        }
    return result


def _load_indicator_map(codes: list[str], start: date, end: date) -> dict[str, dict[str, dict]]:
    fetch_start = start - timedelta(days=120)
    result: dict[str, dict[str, dict]] = {}
    for code in codes:
        indicators = indicators_repo.find_by_code_between(code, fetch_start, end)
        result[code] = {
            str(item.date): item.data or {}
            for item in indicators
        }
    return result


def _load_per_code_regime_map(
    trading_days: list[str],
    code_regime_groups: dict[str, str],
    params: dict,
) -> dict[str, dict[str, dict]]:
    if not trading_days:
        return {}
    start = date.fromisoformat(trading_days[0])
    end = date.fromisoformat(trading_days[-1])
    regimes = market_regime_repo.find_between(start, end)
    base_by_day = {
        str(item.date): {"state": item.state, "score": item.score, "data": item.data}
        for item in regimes
    }
    return {
        day: build_per_code_market_regime(
            code_regime_groups,
            date.fromisoformat(day),
            base_by_day.get(day, {"state": "UNKNOWN"}),
            params=params,
        )
        for day in trading_days
    }


def _future_return(
    *,
    code: str,
    exit_idx: int | None,
    exit_price: float,
    window: int,
    trading_days: list[str],
    price_map: dict[str, dict[str, float]],
) -> float | None:
    if exit_idx is None or exit_price <= 0:
        return None
    future_idx = exit_idx + window
    if future_idx >= len(trading_days):
        return None
    future_price = price_map.get(code, {}).get(trading_days[future_idx])
    if future_price is None or future_price <= 0:
        return None
    return (future_price - exit_price) / exit_price


def _next_closed_trade(
    items: list[dict[str, Any]],
    exit_date: date,
) -> dict[str, Any] | None:
    for item in items:
        if item["entry_date"] > exit_date:
            return item
    return None


def _parse_threshold(reason: str | None) -> float | None:
    if not reason or ":" not in reason:
        return None
    value = reason.split(":", 1)[1].strip().rstrip("%")
    try:
        return float(value) / 100
    except ValueError:
        return None


def _atr_bucket(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value < 0.02:
        return "<2%"
    if value < 0.04:
        return "2-4%"
    if value < 0.06:
        return "4-6%"
    return ">=6%"


def _atr_bucket_sort_key(row: dict[str, Any]) -> int:
    order = {"<2%": 0, "2-4%": 1, "4-6%": 2, ">=6%": 3, "N/A": 4}
    return order.get(row.get("key"), 99)


def _top_rows(
    rows: list[dict[str, Any]],
    *,
    key: str,
    reverse: bool,
    limit: int,
) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: row.get(key) or 0.0, reverse=reverse)[:limit]


def _weighted_avg(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float | None:
    weighted = [
        (row.get(value_key), row.get(weight_key) or 0)
        for row in rows
        if row.get(value_key) is not None and (row.get(weight_key) or 0) > 0
    ]
    total_weight = sum(weight for _value, weight in weighted)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in weighted) / total_weight


def _avg(values) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def _median(values) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return float(median(cleaned))


def _ratio(values: list[float], predicate) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if predicate(value)) / len(values)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_money(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+,.0f}" if signed else f"{value:,.0f}"


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2%}" if signed else f"{value:.2%}"
