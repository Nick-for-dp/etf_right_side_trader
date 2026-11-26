"""市场热度拦截归因分析。

逐笔分析 v2.2 市场热度门控拦截的买入信号，区分 HOT/COLD，
统计拦截后 20/60/120 日收益，输出有效拦截和误拦截分类报告。
"""

from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.advisor import generate_advice
from src.database import indicators_repo, market_regime_repo, quote_repo, signals_repo
from src.service.calendar_service import TradingCalendarService
from src.utils import get_logger

logger = get_logger(__name__)

# 后续收益观察窗口（交易日）
_WINDOWS = [20, 60, 120]
_MARKET_BLOCK_STATES = {
    "HOT",
    "COLD",
    "HOT_RISING",
    "HOT_FALLING",
    "BEAR_TREND",
    "PANIC",
}


def run_attribution(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """运行市场热度拦截归因分析。

    Args:
        codes: ETF 代码列表，None 时覆盖配置中全部
        start: 起始日期
        end:   结束日期

    Returns:
        {
            "meta": {...},
            "summary": {总拦截/有效/误杀统计},
            "by_state": {HOT: {...}, COLD: {...}},
            "by_category": {broad: {...}, sector: {...}},
            "details": [被拦截信号明细],
            "worst_etfs": [变差 ETF 归因],
            "best_etfs": [改善 ETF 归因],
        }
    """
    from src.config import load_config
    config = load_config()

    etf_config_map = {e.symbol: e for e in config.etf_list}

    if codes is None:
        codes = [e.symbol for e in config.etf_list]

    calendar = TradingCalendarService()
    if end is None:
        end_str = calendar.get_previous_trading_day()
        end = date.fromisoformat(end_str)
    if start is None:
        start = end - timedelta(days=config.lookback_days)

    logger.info(f"加载数据: {len(codes)} 只 ETF, {start} ~ {end}")
    price_map, odds_map_full, market_regime_map, _ = _load_data(codes, start, end, calendar)

    # 交易日列表
    trading_days = calendar.get_trading_days_in_range(start, end)
    trading_day_set = set(trading_days)

    # 加载统一信号
    signal_df = _load_signals(codes, start, end)
    sig_by_date: dict[str, list[dict]] = {}
    for _, row in signal_df.iterrows():
        d = row["date"]
        sig_by_date.setdefault(d, []).append(row.to_dict())

    intercepted: list[dict] = []
    all_intercepted_codes: set[str] = set()

    logger.info("逐日分析拦截事件...")
    for day_str in trading_days:
        day_sigs = sig_by_date.get(day_str, [])
        if not day_sigs:
            continue

        regime = market_regime_map.get(day_str)
        if regime is None:
            continue

        market_state = regime.get("state", "UNKNOWN")
        if market_state not in _MARKET_BLOCK_STATES:
            continue

        # 比较 v2.1A（赔率无市场） vs v2.2（赔率+市场）
        odds_only_advices = generate_advice(
            positions=[],
            signals=pd.DataFrame(day_sigs),
            current_prices={},
            risk_signals={},
            odds_map=_build_day_odds(day_sigs, odds_map_full, day_str),
            market_regime=None,
        )
        full_advices = generate_advice(
            positions=[],
            signals=pd.DataFrame(day_sigs),
            current_prices={},
            risk_signals={},
            odds_map=_build_day_odds(day_sigs, odds_map_full, day_str),
            market_regime=regime,
        )

        odds_only_map = {a["code"]: a["advice"] for a in odds_only_advices}
        for adv in full_advices:
            code = adv["code"]
            original = odds_only_map.get(code, "")
            final_advice = adv["advice"]
            source = adv.get("signal_source", "")

            if (
                original in ("建仓", "加仓")
                and final_advice != original
                and source == "market_regime"
            ):
                # 被市场热度拦截
                etf_config = etf_config_map.get(code)
                category = etf_config.category if etf_config else "unknown"
                intercept = {
                    "code": code,
                    "date": day_str,
                    "original_advice": original,
                    "final_advice": final_advice,
                    "market_state": market_state,
                    "market_score": regime.get("score"),
                    "odds_state": _get_odds_state(odds_map_full, code, day_str),
                    "category": category,
                }

                # 后续收益
                prices = price_map.get(code, {})
                entry_price = prices.get(day_str)
                if entry_price and entry_price > 0:
                    day_idx = trading_days.index(day_str) if day_str in trading_days else -1
                    for w in _WINDOWS:
                        future_idx = day_idx + w
                        if 0 <= future_idx < len(trading_days):
                            future_day = trading_days[future_idx]
                            future_price = prices.get(future_day)
                            if future_price and future_price > 0:
                                intercept[f"ret_{w}d"] = (future_price - entry_price) / entry_price
                            else:
                                intercept[f"ret_{w}d"] = None
                        else:
                            intercept[f"ret_{w}d"] = None

                intercepted.append(intercept)
                all_intercepted_codes.add(code)

    # ── 分析：按 state / category 聚合 ──
    by_state: dict[str, dict] = {}
    states = sorted({i["market_state"] for i in intercepted})
    for state in states:
        items = [i for i in intercepted if i["market_state"] == state]
        by_state[state] = _summarize_group(items)

    by_cat: dict[str, dict] = {}
    for cat in ("broad", "sector"):
        items = [i for i in intercepted if i.get("category") == cat]
        by_cat[cat] = _summarize_group(items)

    total = _summarize_group(intercepted)

    # ── 变差/改善 ETF 归因 ──
    etf_stats: dict[str, dict] = {}
    for code in sorted(all_intercepted_codes):
        items = [i for i in intercepted if i["code"] == code]
        etf_stats[code] = _summarize_group(items)

    result = {
        "meta": {"start": str(start), "end": str(end), "codes": codes, "total": len(intercepted)},
        "summary": total,
        "by_state": by_state,
        "by_category": by_cat,
        "details": intercepted,
        "by_etf": etf_stats,
    }

    logger.info(f"归因完成，共 {len(intercepted)} 次拦截")
    return result


# ── 数据加载 ──


def _load_data(codes, start, end, calendar):
    """加载行情、赔率、市场热度数据。"""
    fetch_start = start - timedelta(days=120)
    price_map: dict = {}
    odds_map_full: dict = {}
    for code in codes:
        quotes = quote_repo.find_by_code_in_range(code, fetch_start, end)
        price_map[code] = {str(q.date): float(q.close) for q in quotes}

        indicators = indicators_repo.find_by_code_between(code, fetch_start, end)
        code_odds = {}
        for ind in indicators:
            d_str = str(ind.date)
            os = ind.data.get("odds_state")
            if os is not None:
                code_odds[d_str] = {
                    "odds_state": os,
                    "odds_score": ind.data.get("odds_score"),
                    "premium_blocked": ind.data.get("odds_premium_blocked", False),
                }
        odds_map_full[code] = code_odds

    regimes = market_regime_repo.find_between(start, end)
    market_regime_map = {
        str(r.date): {"state": r.state, "score": r.score, "data": r.data}
        for r in regimes
    }
    trading_days = calendar.get_trading_days_in_range(start, end)
    return price_map, odds_map_full, market_regime_map, trading_days


def _load_signals(codes, start, end):
    """加载统一的信号 DataFrame。"""
    rows = []
    for code in codes:
        sigs = signals_repo.find_by_code_between(code, start, end)
        for s in sigs:
            rows.append({
                "code": code, "date": str(s.date),
                "signal": s.signal, "signal_meta": s.signal_meta or {},
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)


def _build_day_odds(day_sigs, odds_map_full, day_str):
    """构建当日 odds_map。"""
    odds_map = {}
    for sig in day_sigs:
        code = sig["code"]
        co = odds_map_full.get(code, {}).get(day_str)
        if co:
            odds_map[code] = co
    return odds_map


def _get_odds_state(odds_map_full, code, day_str):
    """获取当日赔率状态。"""
    co = odds_map_full.get(code, {}).get(day_str)
    return co.get("odds_state") if co else None


def _summarize_group(items: list[dict]) -> dict:
    """统计一组拦截事件的聚合指标。"""
    n = len(items)
    if n == 0:
        return {"count": 0}

    result = {"count": n}
    for w in _WINDOWS:
        fwd = [i.get(f"ret_{w}d") for i in items if i.get(f"ret_{w}d") is not None]
        if fwd:
            result[f"ret_{w}d_avg"] = sum(fwd) / len(fwd)
            result[f"ret_{w}d_pos"] = sum(1 for v in fwd if v > 0)
            result[f"ret_{w}d_neg"] = sum(1 for v in fwd if v < 0)
            result[f"ret_{w}d_pos_rate"] = sum(1 for v in fwd if v > 0) / len(fwd)
        else:
            result[f"ret_{w}d_avg"] = None
            result[f"ret_{w}d_pos_rate"] = None

    # 有效拦截：后续 60 日收益为负 → 避免了亏损
    result["effective_60d"] = sum(
        1 for i in items if i.get("ret_60d") is not None and i["ret_60d"] < 0
    )
    result["missed_60d"] = sum(
        1 for i in items if i.get("ret_60d") is not None and i["ret_60d"] > 0
    )
    result["effective_rate"] = (
        result["effective_60d"] / (result["effective_60d"] + result["missed_60d"])
        if (result["effective_60d"] + result["missed_60d"]) > 0
        else None
    )

    return result


def format_attribution_report(result: dict[str, Any]) -> str:
    """格式化为可读的归因报告。"""
    lines = []
    lines.append("=" * 72)
    lines.append("  市场热度拦截归因报告")
    lines.append("=" * 72)
    meta = result["meta"]
    lines.append(f"  回测区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append(f"  总拦截次数: {meta['total']}")
    lines.append("")

    s = result["summary"]
    lines.append(f"【全量汇总】共 {s['count']} 次拦截")
    _write_summary(lines, s)

    lines.append("")
    lines.append("-" * 72)

    state_labels = {
        "HOT": "HOT 拦截",
        "COLD": "COLD 拦截",
        "HOT_RISING": "HOT_RISING 过热上涨拦截",
        "HOT_FALLING": "HOT_FALLING 过热回落拦截",
        "BEAR_TREND": "BEAR_TREND 下跌趋势拦截",
        "PANIC": "PANIC 恐慌拦截",
    }
    for key in sorted(result["by_state"]):
        label = state_labels.get(key, key)
        bs = result["by_state"].get(key, {})
        if bs.get("count", 0) > 0:
            lines.append(f"\n【{label}】共 {bs['count']} 次")
            _write_summary(lines, bs)

    lines.append("")
    lines.append("-" * 72)

    for label, key in [("宽基 ETF", "broad"), ("行业 ETF", "sector")]:
        bc = result["by_category"].get(key, {})
        if bc.get("count", 0) > 0:
            lines.append(f"\n【{label}】共 {bc['count']} 次")
            _write_summary(lines, bc)

    lines.append("")
    lines.append("-" * 72)
    lines.append("\n【按 ETF 明细】")
    etf_data = []
    for code, stats in sorted(result.get("by_etf", {}).items()):
        if stats.get("count", 0) > 0:
            avg_20d = stats.get("ret_20d_avg")
            avg_60d = stats.get("ret_60d_avg")
            eff = stats.get("effective_rate")
            etf_data.append([
                code,
                str(stats["count"]),
                f"{avg_20d:+.2%}" if avg_20d is not None else "N/A",
                f"{avg_60d:+.2%}" if avg_60d is not None else "N/A",
                f"{eff:.0%}" if eff is not None else "N/A",
            ])

    if etf_data:
        lines.append(f"  {'代码':>6s}  {'拦截数':>6s}  {'20日均值':>8s}  {'60日均值':>8s}  {'有效拦截率':>8s}")
        for row in etf_data:
            lines.append(f"  {row[0]:>6s}  {row[1]:>6s}  {row[2]:>8s}  {row[3]:>8s}  {row[4]:>8s}")

    return "\n".join(lines)


def _write_summary(lines: list[str], s: dict) -> None:
    """写入单组拦截指标的汇总行。"""
    for w in _WINDOWS:
        avg = s.get(f"ret_{w}d_avg")
        pos_rate = s.get(f"ret_{w}d_pos_rate")
        if avg is not None:
            lines.append(f"  拦截后 {w:3d} 日平均收益: {avg:+.2%}  上涨占比: {pos_rate:.0%}" if pos_rate is not None else "")
    eff = s.get("effective_rate")
    if eff is not None:
        lines.append(f"  有效拦截率（60 日亏损）: {eff:.0%}  ({s.get('effective_60d', 0)}/{s.get('effective_60d', 0) + s.get('missed_60d', 0)})")
