"""策略对比：V1.2 vs V2.0 同数据源双策略回测对比。

基于 BacktestComparison 引擎，在同一份指标 + 行情数据上分别运行
双均线交叉策略（v1.2）和多指标综合评分策略（v2.0），对比交易表现。
趋势跟踪策略在单边市场中多数交易未平仓属正常现象——资金曲线反映累计权益变化。
"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import load_config
from src.service import TradingCalendarService, BacktestComparison
from src.strategy.ma_cross_macd import MaCrossMacdStrategy
from src.strategy.multi_indicator_scoring import MultiIndicatorScoring

_CONFIG = load_config()
_CALENDAR = TradingCalendarService()
_SYMBOL_TO_NAME = {e.symbol: e.name for e in _CONFIG.etf_list}


# ── 辅助函数 ──

def _total_unrealized_pnl(trades: list) -> float:
    """计算所有未平仓交易的累计未实现盈亏（加权平均）。"""
    open_trades = [t for t in trades if t.exit_date is None and t.pnl_pct is not None]
    if not open_trades:
        return 0.0
    return round(sum(t.pnl_pct for t in open_trades), 6)


def _latest_equity(eq_df: pd.DataFrame) -> float | None:
    """取权益曲线最新值。"""
    if eq_df.empty:
        return None
    return float(eq_df["equity"].iloc[-1])


def _per_etf_summary(trades: list, codes: list[str]) -> dict:
    """按 ETF 汇总：已平仓 + 未平仓分别统计。"""
    result = {}
    for code in codes:
        code_trades = [t for t in trades if t.code == code]
        closed = [t for t in code_trades if t.exit_date is not None]
        open_pos = [t for t in code_trades if t.exit_date is None]
        wins = [t for t in closed if t.pnl_pct and t.pnl_pct > 0]
        result[code] = {
            "closed_count": len(closed),
            "open_count": len(open_pos),
            "cum_pnl": round(sum(t.pnl_pct or 0 for t in closed), 6),
            "unrealized": round(sum(t.pnl_pct or 0 for t in open_pos), 6),
            "win_rate": round(len(wins) / len(closed), 4) if closed else 0.0,
        }
    return result


# ── 主页面 ──

def run():
    st.header("策略对比")
    st.caption(
        "V1.2（双均线交叉 + MACD 确认）vs V2.0（多指标综合评分），"
        "同一份指标 + 行情数据上对比。趋势跟踪策略在单边市场中大部分仓位未平仓属正常现象。"
    )

    # ── 策略实例化 ──
    ma_short = _CONFIG.strategy_params.get("ma_short", 20)
    ma_long = _CONFIG.strategy_params.get("ma_long", 60)
    v1_strategy = MaCrossMacdStrategy(ma_short=ma_short, ma_long=ma_long)

    weights = _CONFIG.strategy_params.get("weights", {
        "trend": 0.45, "macd": 0.30, "rsi": 0.15, "bb": 0.10,
    })
    thresholds = _CONFIG.strategy_params.get("thresholds", {
        "buy": 30, "sell": -30,
    })
    v2_strategy = MultiIndicatorScoring(weights=weights, thresholds=thresholds)

    # 加仓冷却期
    cooldown_days = _CONFIG.strategy_params.get("cooldown_days", 5)

    # ── 控制区 ──
    all_codes = [e.symbol for e in _CONFIG.etf_list]
    default_codes = all_codes[:6]

    col1, col2, col3 = st.columns(3)
    with col1:
        selected_codes = st.multiselect(
            "选择 ETF", all_codes, default=default_codes,
            format_func=lambda x: f"{x} — {_SYMBOL_TO_NAME.get(x, '')}"
        )
    with col2:
        end_default = date.today()
        start_default = end_default - timedelta(days=365)
        start_date = st.date_input("起始日期", value=start_default)
    with col3:
        end_date = st.date_input("结束日期", value=end_default)

    run_clicked = st.button("运行对比", type="primary")

    if not run_clicked:
        st.info('选择 ETF 和日期范围后，点击"运行对比"开始回测')
        return

    if not selected_codes:
        st.error("请至少选择一只 ETF")
        return

    if start_date >= end_date:
        st.error("起始日期必须早于结束日期")
        return

    # ── 执行回测 ──
    with st.spinner(f"正在对比 {len(selected_codes)} 只 ETF（{start_date} ~ {end_date}）..."):
        comparator = BacktestComparison(_CALENDAR, cooldown_days=cooldown_days)
        result = comparator.compare(
            v1_strategy=v1_strategy, v2_strategy=v2_strategy,
            codes=selected_codes, start=start_date, end=end_date,
        )

    v1_data = result["v1"]
    v2_data = result["v2"]

    if not v1_data["trades"] and not v2_data["trades"]:
        st.warning("所选区间内两个策略均无交易信号，请扩大日期范围后重试")
        return

    v1_summary = v1_data["summary"]
    v2_summary = v2_data["summary"]
    v1_closed = [t for t in v1_data["trades"] if t.exit_date is not None]
    v2_closed = [t for t in v2_data["trades"] if t.exit_date is not None]
    v1_open = [t for t in v1_data["trades"] if t.exit_date is None]
    v2_open = [t for t in v2_data["trades"] if t.exit_date is None]
    v1_eq_last = _latest_equity(v1_data["equity_curve"])
    v2_eq_last = _latest_equity(v2_data["equity_curve"])

    # ═══════════════════════════════════════════════════════════
    # 一、汇总指标卡片
    # ═══════════════════════════════════════════════════════════

    st.subheader("汇总对比")

    # 第一行：已平仓统计
    st.caption("**已平仓交易**")
    cols_v1 = st.columns(6)
    closed_metrics = [
        ("已平仓次数", len(v1_closed), len(v2_closed), "{:.0f}"),
        ("胜率", v1_summary["win_rate"], v2_summary["win_rate"], "{:.1%}"),
        ("累计已实现", v1_summary["cumulative_pnl_pct"], v2_summary["cumulative_pnl_pct"], "{:+.2%}"),
        ("最大回撤", v1_summary["max_drawdown"], v2_summary["max_drawdown"], "{:+.2%}"),
        ("最大单笔盈利", v1_summary["max_win"], v2_summary["max_win"], "{:+.2%}"),
        ("最大单笔亏损", v1_summary["max_loss"], v2_summary["max_loss"], "{:+.2%}"),
    ]
    for i, (label, v1_val, v2_val, fmt) in enumerate(closed_metrics):
        cols_v1[i].metric(
            f"V1.2 {label}", fmt.format(v1_val),
            delta=f"V2: {fmt.format(v2_val)}" if v1_val != v2_val else None
        )
    cols_v2 = st.columns(6)
    for i, (label, v1_val, v2_val, fmt) in enumerate(closed_metrics):
        delta_val = v2_val - v1_val if isinstance(v1_val, (int, float)) and isinstance(v2_val, (int, float)) else 0
        cols_v2[i].metric(
            f"V2.0 {label}", fmt.format(v2_val),
            delta=f"{delta_val:+.2%}" if abs(delta_val) > 0.0001 and label in ("累计已实现", "胜率") else None
        )

    st.divider()

    # 第二行：未平仓 + 权益统计
    st.caption("**未平仓持仓 & 权益**")
    cols_eq = st.columns(5)
    open_metrics = [
        ("未平仓数", len(v1_open), len(v2_open), "{:.0f}"),
        ("累计未实现", _total_unrealized_pnl(v1_data["trades"]), _total_unrealized_pnl(v2_data["trades"]), "{:+.2%}"),
        ("最新权益", v1_eq_last or 1.0, v2_eq_last or 1.0, "{:.4f}"),
        ("总建仓次数", len(v1_closed) + len(v1_open), len(v2_closed) + len(v2_open), "{:.0f}"),
        ("权益极值(高/低)",
         f"{v1_data['equity_curve']['equity'].max():.4f} / {v1_data['equity_curve']['equity'].min():.4f}" if not v1_data["equity_curve"].empty else "-",
         f"{v2_data['equity_curve']['equity'].max():.4f} / {v2_data['equity_curve']['equity'].min():.4f}" if not v2_data["equity_curve"].empty else "-",
         "{}"),
    ]
    for i, (label, v1_val, v2_val, fmt) in enumerate(open_metrics):
        delta = None
        if isinstance(v1_val, (int, float)) and isinstance(v2_val, (int, float)):
            if label in ("累计未实现", "最新权益"):
                delta = f"{v2_val - v1_val:+.2%}"
        cols_eq[i].metric(f"{label}", fmt.format(v1_val) if isinstance(v1_val, (int, float)) else str(v1_val))
        # Second row below
    cols_eq2 = st.columns(5)
    for i, (label, v1_val, v2_val, fmt) in enumerate(open_metrics):
        delta = None
        if isinstance(v1_val, (int, float)) and isinstance(v2_val, (int, float)):
            if label in ("累计未实现", "最新权益"):
                delta = f"{v2_val - v1_val:+.2%}"
        cols_eq2[i].metric(
            f"V2.0 {label}", fmt.format(v2_val) if isinstance(v2_val, (int, float)) else str(v2_val),
            delta=delta
        )

    st.divider()

    # ═══════════════════════════════════════════════════════════
    # 二、资金曲线叠加图
    # ═══════════════════════════════════════════════════════════

    st.subheader("资金曲线（归一化，起始 = 1.0）")

    v1_eq = v1_data["equity_curve"]
    v2_eq = v2_data["equity_curve"]

    if not v1_eq.empty or not v2_eq.empty:
        fig_eq = go.Figure()

        fig_eq.add_hline(
            y=1.0, line=dict(color="gray", width=0.8, dash="dash"),
            annotation_text="基准 1.0"
        )

        if not v1_eq.empty:
            fig_eq.add_trace(go.Scatter(
                x=v1_eq["date"], y=v1_eq["equity"], mode="lines",
                line=dict(color="#1f77b4", width=2), name="V1.2",
            ))
        if not v2_eq.empty:
            fig_eq.add_trace(go.Scatter(
                x=v2_eq["date"], y=v2_eq["equity"], mode="lines",
                line=dict(color="#ff7f0e", width=2), name="V2.0",
            ))

        fig_eq.update_layout(
            height=450, margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            yaxis_tickformat=".1%",
            hovermode="x unified",
        )
        fig_eq.update_xaxes(title_text="日期")
        fig_eq.update_yaxes(title_text="权益")
        st.plotly_chart(fig_eq, width="stretch")
    else:
        st.info("无足够数据绘制资金曲线")

    st.divider()

    # ═══════════════════════════════════════════════════════════
    # 三、按 ETF 明细表
    # ═══════════════════════════════════════════════════════════

    st.subheader("按 ETF 明细")

    v1_etf = _per_etf_summary(v1_data["trades"], selected_codes)
    v2_etf = _per_etf_summary(v2_data["trades"], selected_codes)

    etf_rows = []
    for code in selected_codes:
        name = _SYMBOL_TO_NAME.get(code, code)
        v1e = v1_etf.get(code, {})
        v2e = v2_etf.get(code, {})
        delta_total = (v2e.get("cum_pnl", 0) or 0) + (v2e.get("unrealized", 0) or 0) - (v1e.get("cum_pnl", 0) or 0) - (v1e.get("unrealized", 0) or 0)
        etf_rows.append({
            "代码": code,
            "名称": name,
            "V1.2 已平仓": v1e.get("closed_count", 0),
            "V1.2 持仓中": v1e.get("open_count", 0),
            "V1.2 累计已实现": f"{v1e.get('cum_pnl', 0):+.2%}",
            "V1.2 未实现": f"{v1e.get('unrealized', 0):+.2%}",
            "V2.0 已平仓": v2e.get("closed_count", 0),
            "V2.0 持仓中": v2e.get("open_count", 0),
            "V2.0 累计已实现": f"{v2e.get('cum_pnl', 0):+.2%}",
            "V2.0 未实现": f"{v2e.get('unrealized', 0):+.2%}",
            "总差异": f"{delta_total:+.2%}",
            "_delta": delta_total,
        })

    etf_df = pd.DataFrame(etf_rows)

    def _highlight_delta(val: str) -> str:
        try:
            num = float(val.replace("%", "")) / 100
        except (ValueError, AttributeError):
            return ""
        if num > 0:
            return "color: #dc3545"
        elif num < 0:
            return "color: #28a745"
        return ""

    display_df = etf_df.drop(columns=["_delta"])
    styled = display_df.style.map(_highlight_delta, subset=["总差异"])
    st.dataframe(styled, width="stretch", hide_index=True)

    st.divider()

    # ═══════════════════════════════════════════════════════════
    # 四、已平仓交易分布散点图
    # ═══════════════════════════════════════════════════════════

    st.subheader("已平仓交易分布")

    scatter_data: list[dict] = []
    for ver, trades in [("V1.2", v1_data["trades"]), ("V2.0", v2_data["trades"])]:
        for t in trades:
            if t.exit_date is not None and t.pnl_pct is not None:
                scatter_data.append({
                    "版本": ver,
                    "代码": t.code,
                    "持仓天数": t.holding_days,
                    "收益率": t.pnl_pct * 100,
                })

    if scatter_data:
        scatter_df = pd.DataFrame(scatter_data)
        fig_sc = go.Figure()
        for ver, color in [("V1.2", "#1f77b4"), ("V2.0", "#ff7f0e")]:
            subset = scatter_df[scatter_df["版本"] == ver]
            if subset.empty:
                continue
            fig_sc.add_trace(go.Scatter(
                x=subset["持仓天数"], y=subset["收益率"], mode="markers",
                marker=dict(size=9, color=color, opacity=0.65), name=ver,
                text=subset["代码"],
                hovertemplate="%{text}<br>持仓 %{x} 天<br>收益 %{y:.2f}%<extra></extra>",
            ))
        fig_sc.add_hline(y=0, line=dict(color="gray", width=0.5, dash="dot"))
        fig_sc.update_layout(
            height=400, margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            xaxis_title="持仓天数", yaxis_title="收益率（%）",
            hovermode="closest",
        )
        st.plotly_chart(fig_sc, width="stretch")
    else:
        st.info("所选区间内无已平仓交易——趋势跟踪策略在单边市场中大部分仓位未平仓属正常现象。可参考上方资金曲线对比权益变化。")


if __name__ == "__main__":
    run()
