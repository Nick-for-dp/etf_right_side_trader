"""市场总览：全部 ETF 最新信号表格。"""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.config import load_config
from src.database import signals_repo, indicators_repo, quote_repo, advice_repo
from src.service import TradingCalendarService

_CONFIG = load_config()
_CALENDAR = TradingCalendarService()
_SYMBOL_TO_NAME = {e.symbol: e.name for e in _CONFIG.etf_list}
_SYMBOL_TO_CATEGORY = {e.symbol: e.category for e in _CONFIG.etf_list}


def _latest_trading_day() -> str:
    return _CALENDAR.get_previous_trading_day()


def run():
    st.header("市场总览")

    t_str = _latest_trading_day()
    t = date.fromisoformat(t_str)

    _render_health(t)

    categories = sorted(set(_SYMBOL_TO_CATEGORY.values()))
    selected_cats = st.multiselect(
        "分类筛选", categories, default=categories,
        help="按 ETF 分类筛选，默认显示全部"
    )

    signals = signals_repo.find_by_date(t)
    if not signals:
        st.warning(f"{t_str} 暂无信号数据，请先运行 python main.py run")
        return
    advice_map = {a.code: a for a in advice_repo.find_by_date(t)}

    rows = []
    for sig in signals:
        symbol = sig.code
        cat = _SYMBOL_TO_CATEGORY.get(symbol, "")
        if selected_cats and cat not in selected_cats:
            continue

        name = _SYMBOL_TO_NAME.get(symbol, symbol)
        q = quote_repo.find_quote_on_or_before(symbol, t)
        close = round(q.close, 4) if q else None

        ind_list = indicators_repo.find_by_code_between(
            symbol, t - timedelta(days=5), t
        )
        ind_data = ind_list[-1].data if ind_list else {}
        ma20 = ind_data.get("ma20")
        ma60 = ind_data.get("ma60")
        rsi = ind_data.get("rsi")
        adx = ind_data.get("adx14")

        meta = sig.signal_meta or {}
        score = meta.get("score")
        advice = advice_map.get(symbol)
        if score is not None:
            signal_display = f"{sig.signal} ({score:+.1f})"
        else:
            signal_display = sig.signal

        rows.append({
            "代码": symbol,
            "名称": name,
            "分类": cat,
            "收盘价": f"{close}" if close else "-",
            "MA20": f"{ma20:.4f}" if ma20 else "-",
            "MA60": f"{ma60:.4f}" if ma60 else "-",
            "RSI": f"{rsi:.1f}" if rsi else "-",
            "ADX": f"{adx:.1f}" if adx else "-",
            "信号": signal_display,
            "建议": advice.advice if advice else "",
            "本次预算": _format_ratio(advice.target_budget_ratio if advice else None),
            "本次阶梯": (
                f"第 {advice.entry_add_step} 次加仓"
                if advice and advice.entry_add_step is not None else "-"
            ),
            "Score": f"{advice.score:+.1f}" if advice and advice.score is not None else "-",
            "市场": advice.market_state if advice and advice.market_state else "-",
            "来源": advice.signal_source if advice else "-",
            "止损": advice.stop_loss_profile if advice and advice.stop_loss_profile else "-",
            "拦截/原因": _advice_reason(advice),
        })

    if not rows:
        st.info("筛选条件下无数据")
        return

    df = pd.DataFrame(rows)

    def _highlight_signal(val):
        if val.startswith("BUY"):
            return "background-color: #d4edda; color: #155724"
        elif val.startswith("SELL"):
            return "background-color: #f8d7da; color: #721c24"
        return ""

    styled = df.style.map(_highlight_signal, subset=["信号"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption(f"共 {len(rows)} 只 ETF，数据截止 {t_str}")


def _render_health(t: date) -> None:
    """数据健康摘要：各域最新日期与近 30 个交易日的断档代码数。"""
    days = _CALENDAR.get_trading_days_in_range(t - timedelta(days=45), t)
    expected = {date.fromisoformat(d) for d in days}
    start = min(expected) if expected else t

    def _gap_codes(loader) -> tuple[int, str]:
        gaps, latest = 0, None
        for etf in _CONFIG.etf_list:
            records = loader(etf.symbol, start, t)
            dates = {r.date for r in records}
            if expected - dates:
                gaps += 1
            d = max(dates) if dates else None
            if d and (latest is None or d > latest):
                latest = d
        return gaps, str(latest or "N/A")

    quote_gaps, quote_latest = _gap_codes(quote_repo.find_by_code_in_range)
    ind_gaps, ind_latest = _gap_codes(indicators_repo.find_by_code_between)
    sig_gaps, sig_latest = _gap_codes(signals_repo.find_by_code_between)
    adv_gaps, adv_latest = _gap_codes(advice_repo.find_by_code_between)

    with st.expander("数据健康", expanded=False):
        st.caption(f"基准交易日 {t}，窗口 {start} ~ {t}")
        st.dataframe(pd.DataFrame([
            {"数据域": "行情", "最新": quote_latest, "断档 ETF": quote_gaps},
            {"数据域": "指标", "最新": ind_latest, "断档 ETF": ind_gaps},
            {"数据域": "信号", "最新": sig_latest, "断档 ETF": sig_gaps},
            {"数据域": "建议", "最新": adv_latest, "断档 ETF": adv_gaps},
        ]), use_container_width=True, hide_index=True)
        if any([quote_gaps, ind_gaps, sig_gaps, adv_gaps]):
            st.warning("存在断档，执行 python main.py check-data 查看明细并 run 补齐")
        else:
            st.success("各域数据完整")


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%"


def _advice_reason(advice) -> str:
    if advice is None:
        return "-"
    if advice.blocked_reason:
        return advice.blocked_reason
    meta = advice.advice_meta or {}
    if meta.get("risk_reason"):
        return meta["risk_reason"]
    budget_plan = meta.get("budget_plan") or {}
    if budget_plan.get("stage") == "entry":
        return "建仓预算 70%" if advice.target_budget_ratio is not None else "-"
    if budget_plan.get("stage") == "add":
        return f"加仓预算 {_format_ratio(advice.target_budget_ratio)}"
    return "-"


if __name__ == "__main__":
    run()
