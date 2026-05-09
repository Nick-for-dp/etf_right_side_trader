"""盈亏分析：基于策略建议的虚拟回测。"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import load_config
from src.service import (
    TradingCalendarService,
    reconstruct_trades,
    calculate_equity_curve,
    get_summary,
)

_CONFIG = load_config()
_CALENDAR = TradingCalendarService()
_SYMBOL_TO_NAME = {e.symbol: e.name for e in _CONFIG.etf_list}


def run():
    st.header("盈亏分析")

    symbols = [e.symbol for e in _CONFIG.etf_list]
    all_symbol = "__ALL__"

    col1, col2, col3 = st.columns(3)
    with col1:
        selected = st.selectbox(
            "ETF 代码",
            [all_symbol] + symbols,
            format_func=lambda x: "全部 ETF" if x == all_symbol else f"{x} — {_SYMBOL_TO_NAME.get(x, '')}"
        )
    with col2:
        t_str = _CALENDAR.get_previous_trading_day()
        today = date.fromisoformat(t_str)
        default_start = today - timedelta(days=365)
        start_date = st.date_input("开始日期", value=default_start)
    with col3:
        end_date = st.date_input("结束日期", value=today)

    if start_date >= end_date:
        st.error("开始日期必须早于结束日期")
        return

    target_codes = symbols if selected == all_symbol else [selected]

    # 重建虚拟交易（全量历史），再按日期范围过滤
    all_raw = []
    for code in target_codes:
        all_raw.extend(reconstruct_trades(code, _CALENDAR))
    all_raw.sort(key=lambda t: t.entry_date)

    all_trades = []
    for t in all_raw:
        if t.exit_date is not None:
            if t.exit_date < start_date or t.entry_date > end_date:
                continue
        else:
            if t.entry_date > end_date:
                continue
        all_trades.append(t)

    if not all_trades:
        st.info("所选区间内无虚拟交易或持仓")
        return

    def _color_pnl(val):
        if isinstance(val, str) and val.startswith("+"):
            return "color: #dc3545"
        elif isinstance(val, str) and val.startswith("-"):
            return "color: #28a745"
        return ""

    open_positions = [t for t in all_trades if t.exit_date is None]
    closed_trades = [t for t in all_trades if t.exit_date is not None]

    # -- 当前虚拟持仓 --
    if open_positions:
        st.subheader("当前虚拟持仓")
        pos_rows = []
        for p in open_positions:
            pos_rows.append({
                "ETF 代码": p.code,
                "名称": _SYMBOL_TO_NAME.get(p.code, p.code),
                "入场日": str(p.entry_date),
                "入场价": f"{p.entry_price:.4f}",
                "最新价": f"{p.latest_price:.4f}" if p.latest_price else "-",
                "浮动盈亏%": f"{p.pnl_pct * 100:+.2f}%" if p.pnl_pct is not None else "-",
                "持有天数": p.holding_days,
            })
        pos_df = pd.DataFrame(pos_rows)
        styled_pos = pos_df.style.map(_color_pnl, subset=["浮动盈亏%"])
        st.dataframe(styled_pos, width="stretch", hide_index=True)
        st.divider()

    if not closed_trades:
        st.info("所选区间内无已完成的虚拟交易")
        return

    # -- 汇总指标 --
    summary = get_summary(all_trades)

    st.subheader("汇总指标")
    cols = st.columns(6)
    cols[0].metric("交易次数", summary["total_trades"])
    cols[1].metric("累计盈亏", f"{summary['cumulative_pnl_pct'] * 100:+.2f}%")
    cols[2].metric("胜率", f"{summary['win_rate'] * 100:.1f}%",
                   f"{summary['win_count']}盈 / {summary['loss_count']}亏")
    cols[3].metric("平均盈亏", f"{summary['avg_pnl_pct'] * 100:+.2f}%")
    cols[4].metric("最大盈利", f"{summary['max_win'] * 100:+.2f}%")
    cols[5].metric("最大亏损", f"{summary['max_loss'] * 100:+.2f}%")

    # -- 已平仓交易明细 --
    st.subheader("已平仓交易明细")
    trade_rows = []
    for t in closed_trades:
        trade_rows.append({
            "ETF 代码": t.code,
            "名称": _SYMBOL_TO_NAME.get(t.code, t.code),
            "入场日": str(t.entry_date),
            "入场价": f"{t.entry_price:.4f}",
            "出场日": str(t.exit_date),
            "出场价": f"{t.exit_price:.4f}",
            "持有天数": t.holding_days,
            "盈亏%": f"{t.pnl_pct * 100:+.2f}%",
            "出场原因": t.exit_reason,
        })
    trade_df = pd.DataFrame(trade_rows)

    styled = trade_df.style.map(_color_pnl, subset=["盈亏%"])
    st.dataframe(styled, width="stretch", hide_index=True)

    # -- 资金曲线 --
    st.subheader("资金曲线")

    equity_df = calculate_equity_curve(target_codes, _CALENDAR, start_date, end_date)

    if not equity_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=equity_df["date"], y=equity_df["equity"],
            mode="lines", name="虚拟权益",
            line=dict(color="#1976d2", width=2),
        ))
        fig.add_trace(go.Scatter(
            x=equity_df["date"], y=1.0 + equity_df["realized"],
            mode="lines", name="累计已实现",
            line=dict(color="#dc3545", width=1, dash="dot"),
        ))
        fig.add_hline(y=1.0, line=dict(color="gray", width=0.5, dash="dash"))
        fig.update_layout(
            height=400,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            yaxis_tickformat=".2%",
        )
        fig.update_yaxes(title_text="权益（归一化）")
        st.plotly_chart(fig, width="stretch")

    # -- 按 ETF 盈亏分布 --
    st.subheader("按 ETF 盈亏分布")
    etf_summary = []
    for code in target_codes:
        code_closed = [t for t in closed_trades if t.code == code]
        if code_closed:
            total_pnl = sum(t.pnl_pct for t in code_closed)
            etf_summary.append({
                "ETF 代码": code,
                "名称": _SYMBOL_TO_NAME.get(code, code),
                "交易次数": len(code_closed),
                "累计盈亏%": f"{total_pnl * 100:+.2f}%",
                "平均盈亏%": f"{(total_pnl / len(code_closed)) * 100:+.2f}%",
                "胜率": f"{len([t for t in code_closed if t.pnl_pct > 0]) / len(code_closed) * 100:.1f}%",
            })
    if etf_summary:
        etf_df = pd.DataFrame(etf_summary)
        styled2 = etf_df.style.map(_color_pnl, subset=["累计盈亏%", "平均盈亏%"])
        st.dataframe(styled2, width="stretch", hide_index=True)


if __name__ == "__main__":
    run()
