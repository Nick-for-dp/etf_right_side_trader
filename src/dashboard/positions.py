"""我的持仓：建仓/加仓/减仓 + 当日操作建议。"""

from datetime import date

import pandas as pd
import streamlit as st

from src.config import load_config
from src.database import positions_repo, quote_repo, advice_repo, trade_records_repo
from src.models import TradeAction, TradeRecord
from src.service import TradingCalendarService, PositionService

_CONFIG = load_config()
_CALENDAR = TradingCalendarService()
_SYMBOL_TO_NAME = {e.symbol: e.name for e in _CONFIG.etf_list}


def _latest_trading_day() -> str:
    return _CALENDAR.get_previous_trading_day()


def run():
    st.header("我的持仓")

    t_str = _latest_trading_day()
    t = date.fromisoformat(t_str)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("当前持仓")

        positions = positions_repo.find_all()
        advice_map = {a.code: a.advice for a in advice_repo.find_by_date(t)}

        if not positions:
            st.info("暂无持仓，请在右侧添加")
        else:
            rows = []
            for pos in positions:
                q = quote_repo.find_latest_quote(pos.code)
                close = q.close if q else None
                pnl = (close - pos.cost) / pos.cost if close and pos.cost > 0 else None

                rows.append({
                    "ETF 代码": pos.code,
                    "名称": _SYMBOL_TO_NAME.get(pos.code, pos.code),
                    "保本价": f"{pos.cost:.4f}",
                    "现价": f"{close:.4f}" if close else "-",
                    "盈亏%": f"{pnl * 100:+.2f}%" if pnl is not None else "-",
                    "股数": pos.shares,
                    "入场日": str(pos.entry_date),
                    "建议": advice_map.get(pos.code, ""),
                    "_id": pos.id,
                })

            df_mixed = pd.DataFrame(rows)

            def _color_pnl(val):
                if val == "-":
                    return ""
                if val.startswith("+"):
                    return "color: #dc3545"
                elif val.startswith("-"):
                    return "color: #28a745"
                return ""

            styled = df_mixed.drop(columns=["_id"]).style.map(_color_pnl, subset=["盈亏%"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

            st.divider()
            st.caption("删除持仓")
            ids_to_delete = [pos.id for pos in positions]
            selected_id = st.selectbox(
                "选择要删除的持仓", ids_to_delete,
                format_func=lambda x: f"#{x} {next((p.code for p in positions if p.id == x), '')}"
            )
            if st.button("删除选中持仓", type="secondary"):
                positions_repo.delete_by_id(selected_id)
                st.rerun()

    with col2:
        st.subheader("建仓 / 加仓")

        symbols = [e.symbol for e in _CONFIG.etf_list]
        code = st.selectbox(
            "ETF 代码", symbols,
            format_func=lambda x: f"{x} {_SYMBOL_TO_NAME.get(x, '')}"
        )

        existing = positions_repo.find_by_code(code)
        if existing:
            st.caption(f"当前持仓：保本价 {existing.cost:.4f}，{existing.shares} 股")

        cost = st.number_input("买入价", min_value=0.01, value=1.00, step=0.01, format="%.4f")
        shares = st.number_input("买入份额（手）", min_value=1, value=1000, step=100)
        entry_date = st.date_input("入场日期", value=date.today())

        if st.button("确认建仓/加仓", type="primary"):
            pos = PositionService.add(code, round(cost, 4), shares, entry_date)
            verb = "加仓" if existing else "建仓"
            trade_records_repo.save(TradeRecord(
                code=code,
                action=TradeAction.ADD if existing else TradeAction.BUY,
                trade_date=entry_date,
                price=round(cost, 4),
                shares=shares,
            ))
            st.success(f"已{verb} {code}，均价 {pos.cost:.4f}，{pos.shares} 股")
            st.rerun()

        st.divider()
        st.subheader("减仓")

        held_codes = [p.code for p in positions]
        if not held_codes:
            st.caption("暂无持仓可减")
        else:
            reduce_code = st.selectbox(
                "选择 ETF", held_codes,
                key="reduce_code",
                format_func=lambda x: f"{x} {_SYMBOL_TO_NAME.get(x, '')}"
            )
            pos_for_reduce = next((p for p in positions if p.code == reduce_code), None)
            if pos_for_reduce:
                st.caption(
                    f"当前持仓：保本价 {pos_for_reduce.cost:.4f}，{pos_for_reduce.shares} 股"
                )
            sell_price = st.number_input("卖出价", min_value=0.01, value=1.00, step=0.01, format="%.4f")
            sell_shares = st.number_input(
                "卖出份额（手）", min_value=1, value=100, step=100,
                max_value=pos_for_reduce.shares if pos_for_reduce else 1000,
            )
            if st.button("确认减仓", type="primary"):
                result = PositionService.reduce(reduce_code, sell_shares, round(sell_price, 4))
                trade_records_repo.save(TradeRecord(
                    code=reduce_code,
                    action=TradeAction.SELL if result is None else TradeAction.REDUCE,
                    trade_date=date.today(),
                    price=round(sell_price, 4),
                    shares=sell_shares,
                ))
                if result is None:
                    st.success(f"已清仓 {reduce_code}")
                else:
                    st.success(f"已减仓 {reduce_code}，剩余 {result.shares} 股，保本价 {result.cost:.4f}")
                st.rerun()


if __name__ == "__main__":
    run()
