"""ETF 详情：K 线 + 布林带 + MA 均线 + 信号标记，副图 MACD / RSI / 成交量 / 赔率评分。"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from src.config import load_config
from src.database import quote_repo, indicators_repo, signals_repo
from src.service import TradingCalendarService

_CONFIG = load_config()
_CALENDAR = TradingCalendarService()
_SYMBOL_TO_NAME = {e.symbol: e.name for e in _CONFIG.etf_list}


def run():
    st.header("ETF 详情")

    symbols = [e.symbol for e in _CONFIG.etf_list]
    symbol = st.selectbox(
        "选择 ETF", symbols,
        format_func=lambda x: f"{x} — {_SYMBOL_TO_NAME.get(x, '')}"
    )

    if not symbol:
        return

    t_str = _CALENDAR.get_previous_trading_day()
    today = date.fromisoformat(t_str)
    default_start = today - timedelta(days=90)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("开始日期", value=default_start)
    with col2:
        end_date = st.date_input("结束日期", value=today)

    if start_date >= end_date:
        st.error("开始日期必须早于结束日期")
        return

    quotes = quote_repo.find_by_code_in_range(symbol, start_date, end_date)
    indicators = indicators_repo.find_by_code_between(symbol, start_date, end_date)
    signals = signals_repo.find_by_code_between(symbol, start_date, end_date)

    if not quotes:
        st.warning(f"{symbol} 在所选区间无行情数据")
        return

    qdf = pd.DataFrame([{
        "date": str(q.date), "open": q.open, "high": q.high,
        "low": q.low, "close": q.close, "volume": q.volume,
    } for q in quotes])

    ind_map = {str(i.date): i.data for i in indicators}
    # MA 均线
    qdf["ma20"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("ma20"))
    qdf["ma60"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("ma60"))
    # 布林带
    qdf["bb_upper"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("bb_upper"))
    qdf["bb_lower"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("bb_lower"))
    # MACD
    qdf["dif"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("dif"))
    qdf["dea"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("dea"))
    qdf["macd"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("macd"))
    # RSI
    qdf["rsi"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("rsi"))
    # 成交量均线
    qdf["vol_ma20"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("vol_ma20"))
    # v2.3：ADX 趋势强度
    qdf["adx14"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("adx14"))
    # v2.1A：长期赔率因子
    qdf["odds_score"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("odds_score"))
    qdf["odds_state"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("odds_state"))
    qdf["odds_premium_blocked"] = qdf["date"].map(lambda d: ind_map.get(d, {}).get("odds_premium_blocked", False))

    # ── 信号标记 ──
    sig_map = {str(s.date): s for s in signals}
    buy_dates, buy_prices = [], []
    sell_dates, sell_prices = [], []
    for _, row in qdf.iterrows():
        d = row["date"]
        if d in sig_map:
            s = sig_map[d]
            if s.signal == "BUY":
                buy_dates.append(d)
                buy_prices.append(row["low"] * 0.98)
            elif s.signal == "SELL":
                sell_dates.append(d)
                sell_prices.append(row["high"] * 1.02)

    # ── 五行子图：K线(40%) + 成交量(12%) + MACD(18%) + RSI(15%) + 赔率(15%) ──
    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.40, 0.12, 0.18, 0.15, 0.15],
    )

    # ── Row 1: K 线 + 均线 + 布林带 + 信号 ──
    fig.add_trace(
        go.Candlestick(
            x=qdf["date"], open=qdf["open"], high=qdf["high"],
            low=qdf["low"], close=qdf["close"],
            name="K线",
        ),
        row=1, col=1,
    )

    if qdf["ma20"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["ma20"], mode="lines",
                       line=dict(color="orange", width=1.5), name="MA20"),
            row=1, col=1,
        )
    if qdf["ma60"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["ma60"], mode="lines",
                       line=dict(color="blue", width=1.5), name="MA60"),
            row=1, col=1,
        )

    # 布林带上下轨
    if qdf["bb_upper"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["bb_upper"], mode="lines",
                       line=dict(color="gray", width=1, dash="dash"),
                       name="BB 上轨"),
            row=1, col=1,
        )
    if qdf["bb_lower"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["bb_lower"], mode="lines",
                       line=dict(color="gray", width=1, dash="dash"),
                       name="BB 下轨"),
            row=1, col=1,
        )

    if buy_dates:
        fig.add_trace(
            go.Scatter(x=buy_dates, y=buy_prices, mode="markers",
                       marker=dict(symbol="triangle-up", size=12, color="red"),
                       name="BUY"),
            row=1, col=1,
        )
    if sell_dates:
        fig.add_trace(
            go.Scatter(x=sell_dates, y=sell_prices, mode="markers",
                       marker=dict(symbol="triangle-down", size=12, color="green"),
                       name="SELL"),
            row=1, col=1,
        )

    # ── Row 2: 成交量 + 20 日均量 ──
    colors = ["red" if qdf.loc[i, "close"] >= qdf.loc[i, "open"] else "green"
              for i in range(len(qdf))]
    fig.add_trace(
        go.Bar(x=qdf["date"], y=qdf["volume"], marker_color=colors,
               name="成交量"),
        row=2, col=1,
    )
    if qdf["vol_ma20"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["vol_ma20"], mode="lines",
                       line=dict(color="orange", width=1.2), name="均量 MA20"),
            row=2, col=1,
        )

    # ── Row 3: MACD ──
    if qdf["dif"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["dif"], mode="lines",
                       line=dict(color="orange", width=1.2), name="DIF"),
            row=3, col=1,
        )
    if qdf["dea"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["dea"], mode="lines",
                       line=dict(color="blue", width=1.2), name="DEA"),
            row=3, col=1,
        )
    if qdf["macd"].notna().any():
        macd_colors = [
            "red" if pd.notna(v) and v >= 0 else "green"
            for v in qdf["macd"]
        ]
        fig.add_trace(
            go.Bar(x=qdf["date"], y=qdf["macd"], marker_color=macd_colors,
                   name="MACD 柱"),
            row=3, col=1,
        )

    # ── Row 4: RSI ──
    if qdf["rsi"].notna().any():
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["rsi"], mode="lines",
                       line=dict(color="purple", width=1.5), name="RSI"),
            row=4, col=1,
        )
    # RSI 参考线：70 超买 / 50 中性 / 30 超卖
    for level, color, label in [(70, "red", "超买 70"), (50, "gray", "中性 50"), (30, "green", "超卖 30")]:
        fig.add_hline(y=level, line=dict(color=color, width=0.5, dash="dot"),
                      row=4, col=1, annotation_text=label,
                      annotation_position="right")

    # ── Row 5: 长期赔率评分 + 三色背景带 ──
    if qdf["odds_score"].notna().any():
        # 三色背景带：CHEAP(≥30) 绿色 / FAIR(-30~30) 留白 / EXPENSIVE(≤-30) 红色
        fig.add_hrect(y0=30, y1=100, fillcolor="rgba(0,180,0,0.08)",
                      line_width=0, row=5, col=1)
        fig.add_hrect(y0=-100, y1=-30, fillcolor="rgba(220,0,0,0.08)",
                      line_width=0, row=5, col=1)
        # 阈值参考线
        fig.add_hline(y=30, line=dict(color="green", width=0.6, dash="dot"),
                      row=5, col=1, annotation_text="CHEAP +30",
                      annotation_position="top right")
        fig.add_hline(y=-30, line=dict(color="red", width=0.6, dash="dot"),
                      row=5, col=1, annotation_text="EXPENSIVE -30",
                      annotation_position="bottom right")
        fig.add_hline(y=0, line=dict(color="gray", width=0.4, dash="dot"),
                      row=5, col=1)
        fig.add_trace(
            go.Scatter(x=qdf["date"], y=qdf["odds_score"], mode="lines",
                       line=dict(color="#1f77b4", width=1.5), name="赔率评分"),
            row=5, col=1,
        )

    # ── 全局布局 ──
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=1000,
        margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_yaxes(title_text="价格", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    fig.update_yaxes(title_text="MACD", row=3, col=1)
    fig.update_yaxes(title_text="RSI", row=4, col=1, range=[0, 100])
    fig.update_yaxes(title_text="赔率评分", row=5, col=1, range=[-100, 100])

    st.plotly_chart(fig, use_container_width=True)

    # ── 底部指标卡片 ──
    st.divider()
    latest = qdf.iloc[-1]
    latest_ind = ind_map.get(latest["date"], {})
    latest_sig = sig_map.get(latest["date"])

    cols = st.columns(11)
    cols[0].metric("最新收盘", f"{latest['close']:.4f}")
    cols[1].metric("MA20",
                   f"{latest_ind.get('ma20', '-'):.4f}" if latest_ind.get("ma20") else "-")
    cols[2].metric("MA60",
                   f"{latest_ind.get('ma60', '-'):.4f}" if latest_ind.get("ma60") else "-")
    cols[3].metric("RSI",
                   f"{latest_ind.get('rsi', '-'):.1f}" if latest_ind.get("rsi") else "-")
    cols[4].metric("量比",
                   f"{latest_ind.get('vol_ratio', '-'):.2f}" if latest_ind.get("vol_ratio") else "-")
    cols[5].metric("区间最高", f"{qdf['high'].max():.4f}")
    cols[6].metric("区间最低", f"{qdf['low'].min():.4f}")
    cols[7].metric(
        "ADX",
        f"{latest_ind.get('adx14', '-'):.1f}" if latest_ind.get("adx14") else "-"
    )

    # ── v2.1A：赔率指标卡片 ──
    odds_score_val = latest_ind.get("odds_score")
    odds_state_val = latest_ind.get("odds_state")
    odds_blocked = latest_ind.get("odds_premium_blocked", False)

    if odds_score_val is not None:
        cols[8].metric("赔率评分", f"{odds_score_val:+.1f}")
    else:
        cols[8].metric("赔率评分", "-")

    if odds_state_val:
        state_color = {
            "CHEAP": "green",
            "FAIR": "gray",
            "EXPENSIVE": "red",
            "INSUFFICIENT": "orange",
        }.get(odds_state_val, "gray")
        cols[9].markdown(
            f"**赔率状态**<br><span style='color:{state_color};font-size:1.2em;font-weight:bold'>{odds_state_val}</span>",
            unsafe_allow_html=True,
        )
        # 溢价拦截警告
        if odds_blocked:
            st.warning(f"⚠ 溢价率过高，新开仓/加仓已被拦截")
    else:
        cols[9].metric("赔率状态", "-")

    # 信号卡片：V2.3 展示评分，V1.x 展示信号字符串
    if latest_sig:
        meta = latest_sig.signal_meta or {}
        score = meta.get("score")
        if score is not None:
            sig_display = f"{latest_sig.signal} ({score:+.1f})"
        else:
            trend = meta.get("trend", "")
            sig_display = f"{latest_sig.signal} ({trend})" if trend else latest_sig.signal
        cols[10].metric("最新信号", sig_display)


if __name__ == "__main__":
    run()
