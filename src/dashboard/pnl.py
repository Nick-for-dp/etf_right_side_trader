"""盈亏分析：基于净值回测引擎的组合收益分析。"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.backtest.portfolio_metrics import open_positions_from_trades, pair_closed_trades
from src.config import load_config
from src.backtest.portfolio_backtest import run_portfolio_backtest
from src.database import quote_repo
from src.service import TradingCalendarService

_CONFIG = load_config()
_CALENDAR = TradingCalendarService()
_SYMBOL_TO_NAME = {e.symbol: e.name for e in _CONFIG.etf_list}
_DEFAULT_CAPITAL = 150_000.0


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

    # ── 运行净值回测 ──
    with st.spinner(f"正在回测 {len(target_codes)} 只 ETF..."):
        result = run_portfolio_backtest(
            codes=target_codes,
            start=start_date,
            end=end_date,
            capital=_DEFAULT_CAPITAL,
        )

    selected_result = result["versions"].get("v2.3-full-gate") or result["versions"].get("v2.2")
    if selected_result is None:
        st.info("所选区间内无信号数据")
        return

    trades = selected_result.get("trades", [])
    equity_curve = selected_result.get("equity_curve", [])
    summary = selected_result.get("summary", {})
    stats = selected_result.get("stats", {})

    if not trades and not equity_curve:
        st.info("所选区间内无交易记录")
        return

    closed_trades = pair_closed_trades(trades)
    open_positions = open_positions_from_trades(trades)

    def _color_pnl(val):
        if isinstance(val, str) and val.startswith("+"):
            return "color: #dc3545"
        elif isinstance(val, str) and val.startswith("-"):
            return "color: #28a745"
        return ""

    # ── 当前持仓 ──
    if open_positions:
        st.subheader("回测未平仓持仓")
        pos_rows = []
        for p in open_positions:
            latest_quote = quote_repo.find_latest_quote(p["code"])
            latest_close = latest_quote.close if latest_quote else None
            current_value = p["shares"] * latest_close if latest_close else None
            pnl_pct = (
                (current_value - p["cash_outflow"]) / p["cash_outflow"]
                if current_value is not None and p["cash_outflow"] else None
            )
            pos_rows.append({
                "ETF 代码": p["code"],
                "名称": _SYMBOL_TO_NAME.get(p["code"], ""),
                "入场日": str(p["entry_date"]),
                "入场均价": f"{p['entry_price']:.4f}",
                "持有天数": (end_date - p["entry_date"]).days,
                "持仓份额": int(p["shares"]),
                "投入资金": f"{p['cash_outflow']:,.0f}",
                "最新浮盈%": f"{pnl_pct * 100:+.2f}%" if pnl_pct is not None else "-",
            })
        styled_pos = pd.DataFrame(pos_rows).style.map(_color_pnl, subset=["最新浮盈%"])
        st.dataframe(styled_pos, use_container_width=True, hide_index=True)
        st.divider()

    # ── 汇总指标 ──
    st.subheader("汇总指标")

    total_trades = len(closed_trades)
    win_count = sum(1 for t in closed_trades if t["pnl_cash"] > 0)
    loss_count = total_trades - win_count
    win_rate = win_count / total_trades if total_trades > 0 else 0
    realized_pnl = sum(t["pnl_cash"] for t in closed_trades)
    avg_pnl = realized_pnl / total_trades if total_trades > 0 else 0
    max_win = max((t["pnl_pct"] for t in closed_trades), default=0)
    max_loss = min((t["pnl_pct"] for t in closed_trades), default=0)

    cols = st.columns(6)
    cols[0].metric("交易次数", total_trades)
    cols[1].metric("已实现盈亏", f"{realized_pnl:,.0f} 元")
    cols[2].metric("胜率", f"{win_rate * 100:.1f}%",
                   f"{win_count}盈 / {loss_count}亏")
    cols[3].metric("平均每笔盈亏", f"{avg_pnl:,.0f} 元")
    cols[4].metric("最大盈利", f"{max_win * 100:+.2f}%")
    cols[5].metric("最大亏损", f"{max_loss * 100:+.2f}%")

    # 额外信息行
    meta_cols = st.columns(3)
    meta_cols[0].metric("初始资金", f"{_DEFAULT_CAPITAL:,.0f} 元")
    meta_cols[1].metric("最终权益", f"{equity_curve[-1].total_equity:,.0f} 元" if equity_curve else "N/A")
    market_blocked = stats.get("market_blocked", 0)
    meta_cols[2].metric("市场拦截", market_blocked)

    if closed_trades:
        # ── 已平仓交易明细 ──
        st.subheader("已平仓交易明细")
        trade_rows = []
        for t in closed_trades:
            trade_rows.append({
                "ETF 代码": t["code"],
                "名称": _SYMBOL_TO_NAME.get(t["code"], ""),
                "入场日": str(t["entry_date"]),
                "入场均价": f"{t['entry_price']:.4f}",
                "出场日": str(t["exit_date"]),
                "出场价": f"{t['exit_price']:.4f}",
                "持有天数": t["holding_days"],
                "投入资金": f"{t['cash_outflow']:,.0f}",
                "盈亏金额": f"{t['pnl_cash']:+,.0f}",
                "盈亏%": f"{t['pnl_pct'] * 100:+.2f}%",
            })
        trade_df = pd.DataFrame(trade_rows)
        styled = trade_df.style.map(_color_pnl, subset=["盈亏金额", "盈亏%"])
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.info("所选区间内无已平仓交易")

    # ── 资金曲线 ──
    st.subheader("资金曲线")

    if equity_curve:
        eq_df = pd.DataFrame([{
            "date": e.date,
            "equity_norm": e.total_equity / _DEFAULT_CAPITAL,
            "total_equity": e.total_equity,
            "cash": e.cash,
            "market_value": e.market_value,
        } for e in equity_curve]).sort_values("date").drop_duplicates("date", keep="last")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=eq_df["date"], y=eq_df["equity_norm"],
            mode="lines", name="组合净值",
            line=dict(color="#1976d2", width=2),
        ))
        fig.add_trace(go.Scatter(
            x=eq_df["date"], y=eq_df["cash"] / _DEFAULT_CAPITAL,
            mode="lines", name="现金比例",
            line=dict(color="#28a745", width=1, dash="dot"),
        ))
        fig.add_hline(y=1.0, line=dict(color="gray", width=0.5, dash="dash"))
        fig.update_layout(
            height=400,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            yaxis_tickformat=".2%",
        )
        fig.update_yaxes(title_text="净值（归一化）")
        st.plotly_chart(fig, use_container_width=True)

        # 净值关键指标
        final_nav = eq_df["equity_norm"].iloc[-1]
        peak = eq_df["equity_norm"].cummax()
        dd = (peak - eq_df["equity_norm"]) / peak
        max_dd = dd.max()
        total_return = final_nav - 1.0

        dd_cols = st.columns(3)
        dd_cols[0].metric("累计收益率", f"{total_return * 100:+.2f}%")
        dd_cols[1].metric("最大回撤（净值口径）", f"{max_dd * 100:.2f}%")
        n_days = len(eq_df)
        if n_days > 0 and max_dd > 0:
            ann_return = (1 + total_return) ** (252 / n_days) - 1
            calmar = ann_return / max_dd if max_dd > 0 else 0
            dd_cols[2].metric("Calmar 比率", f"{calmar:.4f}")

    # ── 按 ETF 盈亏分布 ──
    st.subheader("按 ETF 盈亏分布")
    etf_summary = []
    for code in target_codes:
        code_closed = [t for t in closed_trades if t["code"] == code]
        if code_closed:
            total_pnl_cash = sum(t["pnl_cash"] for t in code_closed)
            total_invested = sum(t["cash_outflow"] for t in code_closed)
            total_pnl_pct = total_pnl_cash / total_invested if total_invested else 0
            etf_summary.append({
                "ETF 代码": code,
                "名称": _SYMBOL_TO_NAME.get(code, ""),
                "交易次数": len(code_closed),
                "已实现盈亏": f"{total_pnl_cash:+,.0f}",
                "累计收益率": f"{total_pnl_pct * 100:+.2f}%",
                "平均单笔": f"{total_pnl_cash / len(code_closed):+,.0f}",
                "胜率": f"{len([t for t in code_closed if t['pnl_cash'] > 0]) / len(code_closed) * 100:.1f}%",
            })
    if etf_summary:
        etf_df = pd.DataFrame(etf_summary)
        styled2 = etf_df.style.map(_color_pnl, subset=["已实现盈亏", "累计收益率", "平均单笔"])
        st.dataframe(styled2, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    run()
