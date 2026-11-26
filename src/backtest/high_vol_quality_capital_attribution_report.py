"""Capital reallocation attribution for high-vol quality-tier experiments."""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from src.backtest.ablation_config import high_vol_quality_tier_candidate_experiments
from src.backtest.ablation_report import run_ablation_backtest
from src.backtest.portfolio_metrics import open_positions_from_trades, pair_closed_trades
from src.database import quote_repo
from src.service.calendar_service import TradingCalendarService

BASELINE_NAME = "baseline_v2_4_segment_stop"
MIXED_NAME = "mixed_high_vol_signal"
TIER_NAME = "high_vol_quality_budget_tier"


def run_high_vol_quality_capital_attribution_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run capital reallocation attribution for baseline/mixed/quality-tier."""
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
    experiments = high_vol_quality_tier_candidate_experiments()

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
            matrix="high-vol-quality-capital-attribution",
        )
        result["meta"]["window"] = label
        result["meta"]["baseline_name"] = BASELINE_NAME
        result["meta"]["mixed_name"] = MIXED_NAME
        result["meta"]["tier_name"] = TIER_NAME
        price_map = _load_price_map(selected_codes, start, window_end)
        attribution = {
            name: _attribute_version(
                item,
                price_map=price_map,
                code_meta=code_meta,
            )
            for name, item in result.get("versions", {}).items()
        }
        window_results.append({"result": result, "attribution": attribution})

    return {
        "meta": {
            "codes": selected_codes,
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "high-vol-quality-capital-attribution",
            "baseline_name": BASELINE_NAME,
            "mixed_name": MIXED_NAME,
            "tier_name": TIER_NAME,
        },
        "windows": window_results,
    }


def format_high_vol_quality_capital_attribution_report(result: dict[str, Any]) -> str:
    """Format capital reallocation attribution report."""
    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 150)
    lines.append("  高波质量分层仓位组合资金再分配归因报告")
    lines.append("=" * 150)
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  对比: baseline-v2.4 / 高波新信号混合 / 高波质量分层仓位。")
    lines.append("")

    for window in result.get("windows", []):
        _append_window(lines, window)

    lines.append("  说明:")
    lines.append("  - 暴露为每日收盘持仓市值 / 当日总权益的时间平均。")
    lines.append("  - 买入/卖出现金流来自成交日志；收益贡献为已平仓收益 + 期末未平仓估算收益。")
    lines.append("  - 本归因用于解释组合资金去向，不等同于精确 Brinson 归因。")
    return "\n".join(lines)


def _append_window(lines: list[str], window: dict[str, Any]) -> None:
    result = window["result"]
    attribution = window["attribution"]
    meta = result["meta"]
    versions = result.get("versions", {})
    lines.append(f"  区间: {meta['window']} ({meta['start']} ~ {meta['end']})")
    _append_allocation_table(lines, versions, attribution)
    _append_flow_table(lines, attribution)
    _append_delta_table(lines, attribution)
    _append_etf_delta_table(lines, attribution)
    lines.append("")


def _append_allocation_table(
    lines: list[str],
    versions: dict[str, Any],
    attribution: dict[str, dict[str, Any]],
) -> None:
    headers = ["实验", "年化", "回撤", "Calmar", "现金", "高波", "低波", "A股", "港股", "美股"]
    cols = [16, 9, 9, 8, 8, 8, 8, 8, 8, 8]
    lines.append("  资金暴露")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for name, item in versions.items():
        summary = item.get("summary", {})
        attr = attribution.get(name, {})
        exposure = attr.get("avg_exposure", {})
        exp = item.get("experiment", {})
        label = exp.get("label") or name
        lines.append(
            f"  {label[:16]:16s}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {_fmt_pct(attr.get('avg_cash_ratio')):>8s}"
            f" {_fmt_pct(exposure.get('vol:high_vol')):>8s}"
            f" {_fmt_pct(exposure.get('vol:low_vol')):>8s}"
            f" {_fmt_pct(exposure.get('market:A股')):>8s}"
            f" {_fmt_pct(exposure.get('market:港股')):>8s}"
            f" {_fmt_pct(exposure.get('market:美股')):>8s}"
        )
    lines.append("")


def _append_flow_table(lines: list[str], attribution: dict[str, dict[str, Any]]) -> None:
    headers = ["实验", "高波买入", "高波卖出", "高波净买", "高波收益", "低波买入", "低波卖出", "低波净买", "低波收益"]
    cols = [16, 10, 10, 10, 10, 10, 10, 10, 10]
    lines.append("  交易现金流和收益贡献")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for name in (BASELINE_NAME, MIXED_NAME, TIER_NAME):
        attr = attribution.get(name, {})
        label = attr.get("label", name)
        flows = attr.get("flows", {})
        pnl = attr.get("pnl", {})
        high = flows.get("vol:high_vol", {})
        low = flows.get("vol:low_vol", {})
        lines.append(
            f"  {label[:16]:16s}"
            f" {_fmt_money(high.get('buy')):>10s}"
            f" {_fmt_money(high.get('sell')):>10s}"
            f" {_fmt_money(high.get('net_buy')):>10s}"
            f" {_fmt_money(pnl.get('vol:high_vol')):>10s}"
            f" {_fmt_money(low.get('buy')):>10s}"
            f" {_fmt_money(low.get('sell')):>10s}"
            f" {_fmt_money(low.get('net_buy')):>10s}"
            f" {_fmt_money(pnl.get('vol:low_vol')):>10s}"
        )
    lines.append("")


def _append_delta_table(lines: list[str], attribution: dict[str, dict[str, Any]]) -> None:
    mixed = attribution.get(MIXED_NAME, {})
    tier = attribution.get(TIER_NAME, {})
    if not mixed or not tier:
        return
    rows = [
        ("现金暴露", tier.get("avg_cash_ratio"), mixed.get("avg_cash_ratio"), "pct"),
        ("高波暴露", _exp(tier, "vol:high_vol"), _exp(mixed, "vol:high_vol"), "pct"),
        ("低波暴露", _exp(tier, "vol:low_vol"), _exp(mixed, "vol:low_vol"), "pct"),
        ("A股暴露", _exp(tier, "market:A股"), _exp(mixed, "market:A股"), "pct"),
        ("高波净买", _flow(tier, "vol:high_vol", "net_buy"), _flow(mixed, "vol:high_vol", "net_buy"), "money"),
        ("低波净买", _flow(tier, "vol:low_vol", "net_buy"), _flow(mixed, "vol:low_vol", "net_buy"), "money"),
        ("高波收益", _pnl(tier, "vol:high_vol"), _pnl(mixed, "vol:high_vol"), "money"),
        ("低波收益", _pnl(tier, "vol:low_vol"), _pnl(mixed, "vol:low_vol"), "money"),
    ]
    headers = ["项目", "质量分层", "混合候选", "差异"]
    cols = [12, 12, 12, 12]
    lines.append("  质量分层相对高波混合的再分配差异")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for label, current, base, kind in rows:
        if kind == "pct":
            cur = _fmt_pct(current)
            b = _fmt_pct(base)
            diff = _fmt_pct(None if current is None or base is None else current - base, signed=True)
        else:
            cur = _fmt_money(current)
            b = _fmt_money(base)
            diff = _fmt_money(None if current is None or base is None else current - base, signed=True)
        lines.append(f"  {label[:12]:12s}  {cur:>12s}  {b:>12s}  {diff:>12s}")
    lines.append("")



def _append_etf_delta_table(lines: list[str], attribution: dict[str, dict[str, Any]]) -> None:
    mixed = attribution.get(MIXED_NAME, {})
    tier = attribution.get(TIER_NAME, {})
    if not mixed or not tier:
        return

    exposure_rows = _top_etf_delta_rows(tier, mixed, "avg_code_exposure", limit=5)
    if exposure_rows:
        lines.append("  质量分层相对高波混合的单 ETF 暴露变化")
        _append_etf_rows(lines, exposure_rows, value_kind="exposure")
        lines.append("")

    pnl_rows = _top_etf_delta_rows(tier, mixed, "pnl_by_code", limit=5)
    if pnl_rows:
        lines.append("  质量分层相对高波混合的单 ETF 收益变化")
        _append_etf_rows(lines, pnl_rows, value_kind="pnl")
        lines.append("")


def _append_etf_rows(lines: list[str], rows: list[dict[str, Any]], *, value_kind: str) -> None:
    if value_kind == "exposure":
        headers = ["方向", "代码", "名称", "波动", "市场", "分层暴露", "混合暴露", "差异"]
    else:
        headers = ["方向", "代码", "名称", "波动", "市场", "分层收益", "混合收益", "差异"]
    cols = [6, 9, 14, 8, 6, 10, 10, 10]

    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        if value_kind == "exposure":
            current = _fmt_pct(row["current"])
            base = _fmt_pct(row["base"])
            diff = _fmt_pct(row["diff"], signed=True)
        else:
            current = _fmt_money(row["current"])
            base = _fmt_money(row["base"])
            diff = _fmt_money(row["diff"], signed=True)
        lines.append(
            f"  {row['direction'][:6]:6s}"
            f"  {row['code'][:9]:9s}"
            f"  {row['name'][:14]:14s}"
            f"  {row['volatility_group'][:8]:8s}"
            f"  {row['regime_group'][:6]:6s}"
            f"  {current:>10s}"
            f"  {base:>10s}"
            f"  {diff:>10s}"
        )


def _top_etf_delta_rows(
    current_attr: dict[str, Any],
    base_attr: dict[str, Any],
    field: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    current_values = current_attr.get(field, {})
    base_values = base_attr.get(field, {})
    code_meta = current_attr.get("code_meta") or base_attr.get("code_meta") or {}
    codes = sorted(set(current_values) | set(base_values))
    rows = []
    for code in codes:
        current = float(current_values.get(code, 0.0))
        base = float(base_values.get(code, 0.0))
        diff = current - base
        if abs(diff) < 1e-12:
            continue
        meta = code_meta.get(code, {})
        rows.append({
            "code": code,
            "name": meta.get("name", code),
            "volatility_group": meta.get("volatility_group", "unknown"),
            "regime_group": meta.get("regime_group", "unknown"),
            "current": current,
            "base": base,
            "diff": diff,
            "direction": "增加" if diff > 0 else "减少",
        })

    positive = sorted((row for row in rows if row["diff"] > 0), key=lambda row: row["diff"], reverse=True)
    negative = sorted((row for row in rows if row["diff"] < 0), key=lambda row: row["diff"])
    return positive[:limit] + negative[:limit]

def _load_price_map(codes: list[str], start: date, end: date) -> dict[str, dict[str, float]]:
    fetch_start = start - timedelta(days=5)
    result: dict[str, dict[str, float]] = {}
    for code in codes:
        quotes = quote_repo.find_by_code_in_range(code, fetch_start, end)
        result[code] = {
            str(item.date): float(item.close)
            for item in quotes
            if item.close is not None
        }
    return result


def _attribute_version(
    version_item: dict[str, Any],
    *,
    price_map: dict[str, dict[str, float]],
    code_meta: dict[str, dict[str, str]],
) -> dict[str, Any]:
    trades = version_item.get("trades", [])
    equity_curve = sorted(version_item.get("equity_curve", []), key=lambda item: item.date)
    exp = version_item.get("experiment", {})
    daily = _daily_exposures(equity_curve, trades, price_map, code_meta)
    flows = _trade_flows(trades, code_meta)
    pnl = _pnl_by_group(trades, price_map, code_meta)
    return {
        "label": exp.get("label") or version_item.get("version", ""),
        "code_meta": code_meta,
        "avg_cash_ratio": _avg([row["cash_ratio"] for row in daily]),
        "avg_market_ratio": _avg([row["market_ratio"] for row in daily]),
        "avg_exposure": _avg_group_exposure(daily),
        "avg_code_exposure": _avg_code_exposure(daily),
        "flows": flows,
        "flows_by_code": _trade_flows_by_code(trades),
        "pnl": pnl,
        "pnl_by_code": _pnl_by_code(trades, price_map),
    }


def _daily_exposures(equity_curve, trades, price_map, code_meta):
    positions: dict[str, float] = defaultdict(float)
    trades_by_date: dict[date, list] = defaultdict(list)
    for trade in trades:
        trades_by_date[trade.date].append(trade)

    rows = []
    for point in equity_curve:
        for trade in trades_by_date.get(point.date, []):
            if trade.action in ("BUY", "建仓", "加仓"):
                positions[trade.code] += trade.shares
            elif trade.action == "SELL":
                positions[trade.code] = 0.0

        group_value: dict[str, float] = defaultdict(float)
        code_value: dict[str, float] = defaultdict(float)
        for code, shares in positions.items():
            if shares <= 0:
                continue
            close = price_map.get(code, {}).get(str(point.date))
            if close is None:
                continue
            value = shares * close
            meta = code_meta.get(code, {})
            code_value[code] += value
            group_value[f"vol:{meta.get('volatility_group', 'unknown_vol')}"] += value
            group_value[f"market:{meta.get('regime_group', 'unknown_market')}"] += value
            group_value[f"category:{meta.get('category', 'unknown_category')}"] += value

        total = point.total_equity or 0.0
        rows.append({
            "date": point.date,
            "cash_ratio": point.cash / total if total > 0 else 0.0,
            "market_ratio": point.market_value / total if total > 0 else 0.0,
            "group_ratio": {
                key: value / total if total > 0 else 0.0
                for key, value in group_value.items()
            },
            "code_ratio": {
                key: value / total if total > 0 else 0.0
                for key, value in code_value.items()
            },
        })
    return rows


def _trade_flows(trades, code_meta):
    flows: dict[str, dict[str, float]] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "net_buy": 0.0})
    for trade in trades:
        for key in _group_keys(trade.code, code_meta):
            if trade.action in ("BUY", "建仓", "加仓"):
                amount = trade.cash_before - trade.cash_after
                flows[key]["buy"] += amount
                flows[key]["net_buy"] += amount
            elif trade.action == "SELL":
                amount = trade.cash_after - trade.cash_before
                flows[key]["sell"] += amount
                flows[key]["net_buy"] -= amount
    return {key: dict(value) for key, value in flows.items()}


def _trade_flows_by_code(trades):
    flows: dict[str, dict[str, float]] = defaultdict(lambda: {"buy": 0.0, "sell": 0.0, "net_buy": 0.0})
    for trade in trades:
        if trade.action in ("BUY", "建仓", "加仓"):
            amount = trade.cash_before - trade.cash_after
            flows[trade.code]["buy"] += amount
            flows[trade.code]["net_buy"] += amount
        elif trade.action == "SELL":
            amount = trade.cash_after - trade.cash_before
            flows[trade.code]["sell"] += amount
            flows[trade.code]["net_buy"] -= amount
    return {key: dict(value) for key, value in flows.items()}


def _pnl_by_group(trades, price_map, code_meta):
    pnl: dict[str, float] = defaultdict(float)
    for item in pair_closed_trades(trades):
        for key in _group_keys(item["code"], code_meta):
            pnl[key] += item["pnl_cash"]

    final_day_by_code = {
        code: max(prices) if prices else None
        for code, prices in price_map.items()
    }
    for item in open_positions_from_trades(trades):
        code = item["code"]
        final_day = final_day_by_code.get(code)
        if final_day is None:
            continue
        final_price = price_map.get(code, {}).get(final_day)
        if final_price is None:
            continue
        open_pnl = item["shares"] * final_price - item["cash_outflow"]
        for key in _group_keys(code, code_meta):
            pnl[key] += open_pnl
    return dict(pnl)


def _pnl_by_code(trades, price_map):
    pnl: dict[str, float] = defaultdict(float)
    for item in pair_closed_trades(trades):
        pnl[item["code"]] += item["pnl_cash"]

    final_day_by_code = {
        code: max(prices) if prices else None
        for code, prices in price_map.items()
    }
    for item in open_positions_from_trades(trades):
        code = item["code"]
        final_day = final_day_by_code.get(code)
        if final_day is None:
            continue
        final_price = price_map.get(code, {}).get(final_day)
        if final_price is None:
            continue
        pnl[code] += item["shares"] * final_price - item["cash_outflow"]
    return dict(pnl)


def _group_keys(code: str, code_meta: dict[str, dict[str, str]]) -> list[str]:
    meta = code_meta.get(code, {})
    return [
        f"vol:{meta.get('volatility_group', 'unknown_vol')}",
        f"market:{meta.get('regime_group', 'unknown_market')}",
        f"category:{meta.get('category', 'unknown_category')}",
    ]


def _avg_group_exposure(daily: list[dict[str, Any]]) -> dict[str, float]:
    keys = sorted({key for row in daily for key in row["group_ratio"]})
    return {
        key: _avg([row["group_ratio"].get(key, 0.0) for row in daily]) or 0.0
        for key in keys
    }


def _avg_code_exposure(daily: list[dict[str, Any]]) -> dict[str, float]:
    keys = sorted({key for row in daily for key in row["code_ratio"]})
    return {
        key: _avg([row["code_ratio"].get(key, 0.0) for row in daily]) or 0.0
        for key in keys
    }


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _exp(attr: dict[str, Any], key: str) -> float | None:
    return attr.get("avg_exposure", {}).get(key)


def _flow(attr: dict[str, Any], key: str, field: str) -> float | None:
    return attr.get("flows", {}).get(key, {}).get(field)


def _pnl(attr: dict[str, Any], key: str) -> float | None:
    return attr.get("pnl", {}).get(key)


def _metric(summary: dict[str, Any], key: str) -> str:
    return str(summary.get(key, "N/A"))


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2%}" if signed else f"{value:.2%}"


def _fmt_money(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+,.0f}" if signed else f"{value:,.0f}"
