"""我的持仓：建仓/加仓/减仓 + 当日操作建议。"""

from datetime import date

import pandas as pd
import streamlit as st

from src.config import load_config
from src.database import positions_repo, quote_repo, advice_repo
from src.models import OperationAdvice, Position
from src.service import TradingCalendarService, PositionService

_CONFIG = load_config()
_CALENDAR = TradingCalendarService()
_SYMBOL_TO_NAME = {e.symbol: e.name for e in _CONFIG.etf_list}


def _latest_trading_day() -> str | None:
    return _CALENDAR.get_previous_trading_day()


def run() -> None:
    st.header("我的持仓")

    t_str = _latest_trading_day()
    if t_str is None:
        st.error("无法获取最近交易日")
        return
    t = date.fromisoformat(t_str)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("当前持仓")

        positions: list[Position] = positions_repo.find_all()
        advice_map: dict[str, OperationAdvice] = {
            a.code: a for a in advice_repo.find_by_date(t)
        }

        if not positions:
            st.info("暂无持仓，请在右侧添加")
        else:
            rows = []
            for pos in positions:
                q = quote_repo.find_latest_quote(pos.code)
                close = q.close if q else None
                pnl = (close - pos.cost) / pos.cost if close and pos.cost > 0 else None
                advice = advice_map.get(pos.code)

                rows.append({
                    "ETF 代码": pos.code,
                    "名称": _SYMBOL_TO_NAME.get(pos.code, pos.code),
                    "保本价": f"{pos.cost:.4f}",
                    "现价": f"{close:.4f}" if close else "-",
                    "盈亏%": f"{pnl * 100:+.2f}%" if pnl is not None else "-",
                    "股数": pos.shares,
                    "入场日": str(pos.entry_date),
                    "首次建仓": str(pos.first_entry_date) if pos.first_entry_date else "-",
                    "已加仓": pos.add_count,
                    "建议": advice.advice if advice else "",
                    "本次预算": _format_ratio(advice.target_budget_ratio if advice else None),
                    "目标金额": _execution_amount(advice),
                    "参考股数": _execution_shares(advice),
                    "本次阶梯": (
                        f"第 {advice.entry_add_step} 次加仓"
                        if advice and advice.entry_add_step is not None else "-"
                    ),
                    "持仓阶段": _holding_stage(advice),
                    "下一阶梯": _next_add_step(advice),
                    "Score": f"{advice.score:+.1f}" if advice and advice.score is not None else "-",
                    "市场": advice.market_state if advice and advice.market_state else "-",
                    "来源": advice.signal_source if advice else "-",
                    "止损": advice.stop_loss_profile if advice and advice.stop_loss_profile else "-",
                    "拦截/原因": _advice_reason(advice),
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
            id_to_code: dict[int, str] = {}
            for pos in positions:
                if pos.id is not None:
                    id_to_code[pos.id] = pos.code
            if not id_to_code:
                st.caption("当前持仓缺少数据库 id，无法删除")
            else:
                def _format_position_option(position_id: int) -> str:
                    return f"#{position_id} {id_to_code[position_id]}"

                selected_id: int | None = st.selectbox(
                    "选择要删除的持仓",
                    list(id_to_code.keys()),
                    format_func=_format_position_option,
                )
                if selected_id is not None and st.button("删除选中持仓", type="secondary"):
                    positions_repo.delete_by_id(selected_id)
                    st.rerun()

    with col2:
        st.subheader("建仓 / 加仓")

        symbols: list[str] = [e.symbol for e in _CONFIG.etf_list]
        if not symbols:
            st.error("settings.yaml 未配置 ETF")
            return

        code_option: str | None = st.selectbox(
            "ETF 代码", symbols,
            format_func=lambda x: f"{x} {_SYMBOL_TO_NAME.get(x, '')}"
        )
        if code_option is None:
            return
        code = str(code_option)

        existing = positions_repo.find_by_code(code)
        if existing:
            st.caption(f"当前持仓：保本价 {existing.cost:.4f}，{existing.shares} 股")

        cost = float(st.number_input(
            "买入价", min_value=0.01, value=1.00, step=0.01, format="%.4f"
        ))
        shares = int(st.number_input("买入份额（手）", min_value=1, value=1000, step=100))
        entry_date_value = st.date_input("入场日期", value=date.today())
        if not isinstance(entry_date_value, date):
            st.error("入场日期必须是单个日期")
            return
        entry_date = entry_date_value

        if st.button("确认建仓/加仓", type="primary"):
            pos, action = PositionService.execute_buy(
                code=code,
                price=round(float(cost), 4),
                shares=shares,
                trade_date=entry_date,
            )
            verb = "加仓" if action.value == "ADD" else "建仓"
            st.success(f"已{verb} {code}，均价 {pos.cost:.4f}，{pos.shares} 股")
            st.rerun()

        st.divider()
        st.subheader("减仓")

        held_codes = [p.code for p in positions]
        if not held_codes:
            st.caption("暂无持仓可减")
        else:
            reduce_code_option: str | None = st.selectbox(
                "选择 ETF", held_codes,
                key="reduce_code",
                format_func=lambda x: f"{x} {_SYMBOL_TO_NAME.get(x, '')}"
            )
            if reduce_code_option is None:
                return
            reduce_code = str(reduce_code_option)
            pos_for_reduce = next((p for p in positions if p.code == reduce_code), None)
            if pos_for_reduce is None:
                st.error("未找到可减仓持仓")
                return
            st.caption(
                f"当前持仓：保本价 {pos_for_reduce.cost:.4f}，{pos_for_reduce.shares} 股"
            )
            sell_price = float(st.number_input(
                "卖出价", min_value=0.01, value=1.00, step=0.01, format="%.4f"
            ))
            sell_shares = int(st.number_input(
                "卖出份额（手）", min_value=1, value=100, step=100,
                max_value=pos_for_reduce.shares,
            ))
            if st.button("确认减仓", type="primary"):
                result, _action = PositionService.execute_sell(
                    code=reduce_code,
                    price=round(float(sell_price), 4),
                    shares=sell_shares,
                    trade_date=date.today(),
                )
                if result is None:
                    st.success(f"已清仓 {reduce_code}")
                else:
                    st.success(f"已减仓 {reduce_code}，剩余 {result.shares} 股，保本价 {result.cost:.4f}")
                st.rerun()


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%"


def _execution_meta(advice: OperationAdvice | None) -> dict:
    if advice is None:
        return {}
    return (advice.advice_meta or {}).get("execution") or {}


def _execution_amount(advice: OperationAdvice | None) -> str:
    amount = _execution_meta(advice).get("amount")
    if amount is None:
        return "-"
    return f"{amount:,.0f} 元"


def _execution_shares(advice: OperationAdvice | None) -> str:
    shares = _execution_meta(advice).get("shares")
    if shares is None:
        return "-"
    return f"{shares:,} 股"


def _advice_reason(advice: OperationAdvice | None) -> str:
    if advice is None:
        return "-"
    if advice.blocked_reason:
        return advice.blocked_reason
    meta = advice.advice_meta or {}
    if meta.get("risk_reason"):
        return str(meta["risk_reason"])
    budget_plan = meta.get("budget_plan") or {}
    if budget_plan.get("stage") == "entry":
        return "建仓预算 70%" if advice.target_budget_ratio is not None else "-"
    if budget_plan.get("stage") == "add":
        return f"加仓预算 {_format_ratio(advice.target_budget_ratio)}"
    return "-"


def _holding_stage(advice: OperationAdvice | None) -> str:
    if advice is None:
        return "-"
    meta = advice.advice_meta or {}
    add_count = _to_int(meta.get("add_count"))
    add_steps = _add_steps(meta)
    if add_count is None:
        return "-"
    total_steps = len(add_steps)
    if total_steps == 0:
        return "无加仓阶梯"
    if add_count <= 0:
        return f"已建仓，未加仓/{total_steps}"
    if add_count >= total_steps:
        return f"已完成加仓 {total_steps}/{total_steps}"
    return f"已加仓 {add_count}/{total_steps}"


def _next_add_step(advice: OperationAdvice | None) -> str:
    if advice is None:
        return "-"
    meta = advice.advice_meta or {}
    add_count = _to_int(meta.get("add_count"))
    add_steps = _add_steps(meta)
    if add_count is None or add_count >= len(add_steps):
        return "-"
    step = add_steps[add_count]
    ratio_text = _format_ratio(_to_float(step.get("ratio")))
    requirements = []
    if step.get("require_profit", True):
        requirements.append("需浮盈")
    min_score = step.get("min_score")
    if min_score is not None:
        requirements.append(f"score>={min_score:g}" if isinstance(min_score, (int, float)) else f"score>={min_score}")
    suffix = f" ({', '.join(requirements)})" if requirements else ""
    return f"第 {add_count + 1} 次 {ratio_text}{suffix}"


def _add_steps(meta: dict) -> list[dict]:
    budget = meta.get("entry_add_budget") or {}
    steps = budget.get("add_steps") or []
    return [step for step in steps if isinstance(step, dict)]


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    run()
