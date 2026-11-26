"""止损归因：止损事件与止损后的走势。

只从回测交易记录中提取 signal_source = stop_loss 的退出，
统计退出时的盈亏、之后 20/60 个交易日的收益，并按波动组和 ATR 分桶。
样本极少（历史上 423 笔闭合交易只有 7 次止损），结论仅作参考。
"""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any

from src.backtest.portfolio_backtest import run_portfolio_backtest
from src.backtest.portfolio_metrics import pair_closed_trades
from src.database import indicators_repo, quote_repo

_ATR_BUCKETS = [(0.02, "<2%"), (0.04, "2-4%"), (0.06, "4-6%"), (99, "≥6%")]


def run_stop_loss_attribution_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """运行生产回测，抽取止损事件并统计止损后收益。"""
    from src.config import load_config
    config = load_config()

    result = run_portfolio_backtest(codes=codes, start=start, end=end)
    version = next(iter(result["versions"].values()), {})
    trades = version.get("trades", [])
    if not trades:
        return {"events": [], "summary": {}, "by_group": {}, "by_atr": {}}

    start = date.fromisoformat(result["meta"]["start"])
    end = date.fromisoformat(result["meta"]["end"])

    closed = pair_closed_trades(trades)
    closed_by_key = {(c["code"], c["exit_date"]): c for c in closed}

    vol_groups = {e.symbol: e.volatility_group for e in config.etf_list}
    price_map = _load_price_map(
        sorted({t.code for t in trades if t.signal_source == "stop_loss"}), start, end
    )
    atr_map = _load_atr_map(
        sorted({t.code for t in trades if t.signal_source == "stop_loss"}), start, end
    )

    events: list[dict[str, Any]] = []
    for t in trades:
        if t.signal_source != "stop_loss":
            continue
        close = closed_by_key.get((t.code, t.date), {})
        atr_pct = _latest_atr(atr_map, t.code, t.date)
        events.append({
            "code": t.code,
            "date": t.date,
            "exit_price": t.price,
            "threshold": _parse_threshold(t.reason),
            "pnl_pct": close.get("pnl_pct"),
            "pnl_cash": close.get("pnl_cash"),
            "holding_days": close.get("holding_days"),
            "volatility_group": vol_groups.get(t.code, "unknown_vol"),
            "atr_bucket": _atr_bucket(atr_pct),
            "forward_20d": _forward_return(price_map, t.code, t.date, 20),
            "forward_60d": _forward_return(price_map, t.code, t.date, 60),
        })

    return {
        "events": events,
        "summary": _summarize(events),
        "by_group": _summarize_by(events, "volatility_group"),
        "by_atr": _summarize_by(events, "atr_bucket"),
    }


def format_stop_loss_attribution_report(result: dict[str, Any]) -> str:
    """格式化止损归因报告。"""
    lines = ["=" * 72, "  止损归因报告", "=" * 72]
    s = result["summary"]
    if not s:
        lines.append("  本次回测没有止损事件。")
        return "\n".join(lines)

    lines.append(f"  止损次数: {s['count']}")
    lines.append(f"  止损时平均盈亏: {_fmt_pct(s['avg_pnl_pct'], signed=True)}")
    lines.append(f"  止损后 20 日均值: {_fmt_pct(s['avg_forward_20d'], signed=True)}"
                 f"（上涨占比 {_fmt_pct(s['forward_20d_up_ratio'])}）")
    lines.append(f"  止损后 60 日均值: {_fmt_pct(s['avg_forward_60d'], signed=True)}"
                 f"（上涨占比 {_fmt_pct(s['forward_60d_up_ratio'])}）")
    lines.append("")

    for title, key in (("按波动组", "by_group"), ("按 ATR 分桶", "by_atr")):
        lines.append(f"【{title}】")
        lines.append(f"  {'分组':<12s}{'次数':>6s}{'止损盈亏':>10s}{'20日':>10s}{'60日':>10s}")
        for name, stats in result[key].items():
            lines.append(
                f"  {name:<12s}{stats['count']:>6d}"
                f"{_fmt_pct(stats['avg_pnl_pct'], signed=True):>10s}"
                f"{_fmt_pct(stats['avg_forward_20d'], signed=True):>10s}"
                f"{_fmt_pct(stats['avg_forward_60d'], signed=True):>10s}"
            )
        lines.append("")

    lines.append("【事件明细】")
    for e in result["events"]:
        lines.append(
            f"  {e['code']} {e['date']} 阈值={_fmt_pct(e['threshold'])} "
            f"盈亏={_fmt_pct(e['pnl_pct'], signed=True)} "
            f"20日={_fmt_pct(e['forward_20d'], signed=True)} "
            f"60日={_fmt_pct(e['forward_60d'], signed=True)}"
        )
    return "\n".join(lines)


# ── 统计 ──

def _summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(events),
        "avg_pnl_pct": _avg([e["pnl_pct"] for e in events if e["pnl_pct"] is not None]),
        "median_pnl_pct": _median([e["pnl_pct"] for e in events if e["pnl_pct"] is not None]),
        "avg_forward_20d": _avg([e["forward_20d"] for e in events if e["forward_20d"] is not None]),
        "avg_forward_60d": _avg([e["forward_60d"] for e in events if e["forward_60d"] is not None]),
        "forward_20d_up_ratio": _ratio([e["forward_20d"] for e in events], lambda v: v > 0),
        "forward_60d_up_ratio": _ratio([e["forward_60d"] for e in events], lambda v: v > 0),
    }


def _summarize_by(events: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        groups[e[key]].append(e)
    return {name: _summarize(items) for name, items in sorted(groups.items())}


# ── 数据获取 ──

def _load_price_map(codes: list[str], start: date, end: date) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    fetch_start = start - timedelta(days=60)
    for code in codes:
        quotes = quote_repo.find_by_code_in_range(code, fetch_start, end + timedelta(days=120))
        result[code] = {str(q.date): float(q.close) for q in quotes}
    return result


def _load_atr_map(codes: list[str], start: date, end: date) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for code in codes:
        atr: dict[str, float] = {}
        for ind in indicators_repo.find_by_code_between(code, start, end):
            value = ind.data.get("atr_pct")
            if value is not None:
                atr[str(ind.date)] = float(value)
        result[code] = atr
    return result


def _latest_atr(atr_map: dict[str, dict[str, float]], code: str, on: date) -> float | None:
    """取 on 当日或之前最近一个交易日的 ATR%。"""
    values = atr_map.get(code, {})
    candidates = [d for d in values if d <= str(on)]
    if not candidates:
        return None
    return values[max(candidates)]


def _forward_return(
    price_map: dict[str, dict[str, float]], code: str, exit_date: date, horizon: int,
) -> float | None:
    """止损后第 horizon 个交易日的收盘价相对止损价的收益。"""
    prices = price_map.get(code, {})
    dates = sorted(d for d in prices if d > str(exit_date))
    if len(dates) < horizon:
        return None
    base = prices.get(str(exit_date))
    if base is None or base <= 0:
        return None
    return prices[dates[horizon - 1]] / base - 1.0


# ── 小工具 ──

def _parse_threshold(reason: str | None) -> float | None:
    if not reason or ":" not in reason:
        return None
    tail = reason.rsplit(":", 1)[-1].strip()
    if tail.endswith("%"):
        try:
            return float(tail[:-1]) / 100.0
        except ValueError:
            return None
    return None


def _atr_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    for bound, label in _ATR_BUCKETS:
        if value < bound:
            return label
    return "unknown"


def _avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _median(values) -> float | None:
    values = [v for v in values if v is not None]
    return median(values) if values else None


def _ratio(values: list[float | None], predicate) -> float | None:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(1 for v in values if predicate(v)) / len(values)


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.2%}" if signed else f"{value:.2%}"
