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

    categories = sorted(set(_SYMBOL_TO_CATEGORY.values()))
    selected_cats = st.multiselect(
        "分类筛选", categories, default=categories,
        help="按 ETF 分类筛选，默认显示全部"
    )

    signals = signals_repo.find_by_date(t)
    if not signals:
        st.warning(f"{t_str} 暂无信号数据，请先运行 python main.py run")
        return
    advice_map = {a.code: a.advice for a in advice_repo.find_by_date(t)}

    rows = []
    for sig in signals:
        symbol = sig.code
        cat = _SYMBOL_TO_CATEGORY.get(symbol, "")
        if selected_cats and cat not in selected_cats:
            continue

        name = _SYMBOL_TO_NAME.get(symbol, symbol)
        q = quote_repo.find_latest_quote(symbol)
        close = round(q.close, 4) if q else None
        nav = round(q.nav, 4) if q and q.nav else None

        ind_list = indicators_repo.find_by_code_between(
            symbol, t - timedelta(days=5), t
        )
        ind_data = ind_list[-1].data if ind_list else {}
        ma20 = ind_data.get("ma20")
        ma60 = ind_data.get("ma60")
        rsi = ind_data.get("rsi")
        adx = ind_data.get("adx14")

        meta = sig.signal_meta or {}
        trend = meta.get("trend", "")
        score = meta.get("score")
        # V2.3 展示评分，V1.x 展示趋势
        if score is not None:
            signal_display = f"{sig.signal} ({score:+.1f})"
        elif trend:
            signal_display = f"{sig.signal} ({trend})"
        else:
            signal_display = sig.signal

        rows.append({
            "代码": symbol,
            "名称": name,
            "分类": cat,
            "收盘价": f"{close}" if close else "-",
            "NAV": f"{nav}" if nav else "-",
            "MA20": f"{ma20:.4f}" if ma20 else "-",
            "MA60": f"{ma60:.4f}" if ma60 else "-",
            "RSI": f"{rsi:.1f}" if rsi else "-",
            "ADX": f"{adx:.1f}" if adx else "-",
            "信号": signal_display,
            "建议": advice_map.get(symbol, ""),
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


if __name__ == "__main__":
    run()
