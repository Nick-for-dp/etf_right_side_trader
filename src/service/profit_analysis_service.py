"""虚拟回测盈亏分析：基于 operation_advice 历史重建虚拟交易对，计算盈亏与资金曲线。

纯分析层，不写数据库。数据来源复用 operation_advice + quote 表。
"""

from datetime import date

import pandas as pd

from src.database import advice_repo, quote_repo
from src.models import VirtualTrade
from src.service import TradingCalendarService


# ── 交易模拟引擎（纯函数，与数据源无关）─────────────────────────────

def _simulate_trade_engine(
    events: list[tuple[date, str, float, str]],
    latest_price: float | None = None,
) -> list[VirtualTrade]:
    """纯函数：输入交易事件序列，输出 VirtualTrade 列表。

    状态机逻辑（与 reconstruct_trades 完全一致）：
      - "建仓" / "加仓" → 累加 units，均价重算（total_cost / entry_units）
      - "卖出" → 清仓，结算已平仓交易（已实现盈亏 + 持有天数）
      - 末尾仍有持仓 → 生成 open VirtualTrade（exit_date=None）

    调用方负责将数据源（DB advice / 内存信号）转换为统一的事件格式。

    Args:
        events:       [(exec_date, action, exec_price, exit_reason), ...]，按日期升序
        latest_price: 最新收盘价，用于未平仓持仓的浮动盈亏计算

    Returns:
        VirtualTrade 列表，按入场日期升序
    """
    trades: list[VirtualTrade] = []
    in_position = False
    entry_units = 0
    total_cost = 0.0
    entry_exec_date: date | None = None

    for exec_date, action, exec_price, signal_source in events:
        # ── 入场：建仓 / 加仓 ──
        if action in ("建仓", "加仓") and not in_position:
            in_position = True
            entry_units = 1
            total_cost = exec_price
            entry_exec_date = exec_date

        elif action in ("建仓", "加仓") and in_position:
            # 已在仓内再收到建仓/加仓 → 累加仓位，均价重算
            entry_units += 1
            total_cost += exec_price

        # ── 离场：卖出 ──
        elif action == "卖出" and in_position:
            avg_cost = total_cost / entry_units
            pnl_pct = (exec_price - avg_cost) / avg_cost
            holding_days = (exec_date - entry_exec_date).days

            trades.append(VirtualTrade(
                code="",  # 调用方后续设值，或直接返回不带 code 的记录
                entry_date=entry_exec_date,
                entry_price=round(avg_cost, 4),
                exit_date=exec_date,
                exit_price=round(exec_price, 4),
                pnl_pct=round(pnl_pct, 6),
                holding_days=holding_days,
                exit_reason=signal_source or "trend",
            ))

            in_position = False
            entry_units = 0
            total_cost = 0.0
            entry_exec_date = None

    # ── 末尾未平仓 ──
    if in_position and entry_exec_date is not None:
        avg_cost = total_cost / entry_units
        unrealized = None
        if latest_price is not None:
            unrealized = round((latest_price - avg_cost) / avg_cost, 6)
        holding_days = (date.today() - entry_exec_date).days
        trades.append(VirtualTrade(
            code="",
            entry_date=entry_exec_date,
            entry_price=round(avg_cost, 4),
            pnl_pct=unrealized,
            holding_days=holding_days,
            latest_price=round(latest_price, 4) if latest_price else None,
        ))

    return trades


# ── 公开 API ──

def reconstruct_trades(
    code: str,
    calendar: TradingCalendarService,
) -> list[VirtualTrade]:
    """对单只 ETF 遍历全部 operation_advice 历史，重建虚拟交易。

    成交价取 advice 生成当日的收盘价，杜绝未来函数：
    - 生成当日 = next_trading_day(advice.date)，即 runner 在 advice.date 的下一个交易日 07:00 生成建议
    - 交易者在当日盘中执行，以当日收盘价模拟成交

    Args:
        code:     ETF 代码，如 "588000"
        calendar: 交易日历，用于计算 next_trading_day

    Returns:
        VirtualTrade 列表，按入场日期升序。每条记录：
        - exit_date 有值 → 已平仓，pnl_pct 为已实现盈亏，exit_reason 标注出场原因
        - exit_date 为 None → 持仓中，pnl_pct 为浮动盈亏，latest_price 为最新收盘价

    Example:
        >>> trades = reconstruct_trades("588000", calendar)
        >>> for t in trades:
        ...     status = "已平仓" if t.exit_date else "持仓中"
        ...     print(f"{t.code} {status} {t.pnl_pct}")
    """
    advices = advice_repo.find_by_code(code)
    if not advices:
        return []

    quotes = quote_repo.find_by_code_in_range(code)
    quote_map: dict[str, float] = {str(q.date): float(q.close) for q in quotes}
    latest_price = float(quotes[-1].close) if quotes else None

    # 将 DB advice 转换为事件序列
    events: list[tuple[date, str, float, str]] = []
    for adv in advices:
        exec_date_str = calendar.get_next_trading_day(str(adv.date))
        if exec_date_str is None:
            continue
        exec_date = date.fromisoformat(exec_date_str)

        exec_price = quote_map.get(exec_date_str)
        if exec_price is None:
            continue

        events.append((exec_date, adv.advice, exec_price, adv.signal_source or ""))

    # 调用纯函数引擎
    trades = _simulate_trade_engine(events, latest_price)

    # 回填 code 字段
    for t in trades:
        t.code = code

    return trades


def calculate_equity_curve(
    codes: list[str],
    calendar: TradingCalendarService,
    start: date,
    end: date,
) -> pd.DataFrame:
    """按交易日逐日模拟虚拟持仓，输出每日权益曲线。

    独立于 reconstruct_trades，直接遍历 advice 构建时间线，按交易日维度
    重放建仓/加仓/卖出事件，逐日估值。

    Args:
        codes:    ETF 代码列表
        calendar: 交易日历
        start:    起始日期（含）
        end:      结束日期（含）

    Returns:
        DataFrame，列：
        - date:       交易日
        - realized:   累计已实现盈亏（卖出时结算）
        - unrealized: 当日浮动盈亏（持仓按当日收盘价估值之和）
        - equity:     虚拟权益 = 1.0 + realized + unrealized，归一化，起始 1.0

    Example:
        >>> df = calculate_equity_curve(["588000"], calendar, date(2026, 1, 1), date(2026, 5, 1))
        >>> df["equity"].iloc[-1]  # 最新权益
        1.0234
    """
    # 构建价格映射 {code: {date_str: close}}
    price_map: dict[str, dict[str, float]] = {}
    for code in codes:
        quotes = quote_repo.find_by_code_in_range(code, start, end)
        price_map[code] = {str(q.date): float(q.close) for q in quotes}

    # 构建事件时间线 [(exec_date, code, action, price), ...]
    timeline: list[tuple[date, str, str, float]] = []
    for code in codes:
        advices = advice_repo.find_by_code(code)
        for adv in advices:
            exec_date_str = calendar.get_next_trading_day(str(adv.date))
            if exec_date_str is None:
                continue
            exec_date = date.fromisoformat(exec_date_str)
            price = price_map.get(code, {}).get(exec_date_str)
            if price is None:
                continue
            timeline.append((exec_date, code, adv.advice, price))

    timeline.sort(key=lambda x: x[0])

    trading_days = calendar.get_trading_days_in_range(start, end)

    active_positions: dict[str, dict] = {}
    realized_pnl = 0.0
    rows = []

    for td_str in trading_days:
        td = date.fromisoformat(td_str)

        # 处理当日事件
        for exec_date, code, action, price in timeline:
            if exec_date != td:
                continue

            if action in ("建仓", "加仓"):
                if code not in active_positions:
                    active_positions[code] = {"avg_cost": price, "units": 1}
                else:
                    pos = active_positions[code]
                    total_units = pos["units"] + 1
                    total_cost = pos["avg_cost"] * pos["units"] + price
                    pos["avg_cost"] = total_cost / total_units
                    pos["units"] = total_units

            elif action == "卖出" and code in active_positions:
                pos = active_positions[code]
                trade_pnl = (price - pos["avg_cost"]) / pos["avg_cost"]
                realized_pnl += trade_pnl
                del active_positions[code]

        # 计算当日浮动盈亏
        unrealized_pnl = 0.0
        for code, pos in active_positions.items():
            close_price = price_map.get(code, {}).get(td_str)
            if close_price is not None:
                unrealized_pnl += (close_price - pos["avg_cost"]) / pos["avg_cost"]

        rows.append({
            "date": td,
            "realized": round(realized_pnl, 6),
            "unrealized": round(unrealized_pnl, 6),
            "equity": round(1.0 + realized_pnl + unrealized_pnl, 6),
        })

    return pd.DataFrame(rows)


def get_summary(trades: list[VirtualTrade]) -> dict:
    """从虚拟交易列表中提取汇总指标，仅统计已平仓交易。

    Args:
        trades: VirtualTrade 列表（可含未平仓，内部自动过滤）

    Returns:
        dict:
        - total_trades:      已平仓交易次数
        - win_count:         盈利次数
        - loss_count:        亏损次数
        - win_rate:          胜率（0~1）
        - avg_pnl_pct:       平均盈亏%
        - cumulative_pnl_pct: 累计盈亏%
        - max_win:           最大单笔盈利%
        - max_loss:          最大单笔亏损%
        - max_drawdown:      最大回撤%（peak-to-trough，负值；≤1 笔交易时为 0）
        - avg_holding_days:  平均持有天数

    Example:
        >>> trades = reconstruct_trades("588000", calendar)
        >>> summary = get_summary(trades)
        >>> print(f"胜率: {summary['win_rate']:.1%}, 累计: {summary['cumulative_pnl_pct']:+.2%}")
    """
    closed = sorted(
        [t for t in trades if t.exit_date is not None],
        key=lambda t: t.exit_date,  # type: ignore[arg-type]
    )
    if not closed:
        return {
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0,
            "avg_pnl_pct": 0,
            "cumulative_pnl_pct": 0,
            "max_win": 0,
            "max_loss": 0,
            "max_drawdown": 0,
            "avg_holding_days": 0,
        }

    wins = [t for t in closed if t.pnl_pct and t.pnl_pct > 0]
    losses = [t for t in closed if t.pnl_pct and t.pnl_pct <= 0]

    # 最大回撤：从累计盈亏序列计算 peak-to-trough
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0  # 非负值，取最大跌幅的绝对值（返回时转负）
    for t in closed:
        cum_pnl += (t.pnl_pct or 0.0)
        if cum_pnl > peak:
            peak = cum_pnl
        dd = peak - cum_pnl  # 正值，表示从峰值的回撤幅度
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(closed),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(closed), 4),
        "avg_pnl_pct": round(sum(t.pnl_pct or 0 for t in closed) / len(closed), 6),
        "cumulative_pnl_pct": round(sum(t.pnl_pct or 0 for t in closed), 6),
        "max_win": round(max(t.pnl_pct or 0 for t in closed), 6),
        "max_loss": round(min(t.pnl_pct or 0 for t in closed), 6),
        "max_drawdown": round(-max_dd, 6),  # 转负值：-0.15 表示最大回撤 15%
        "avg_holding_days": round(sum(t.holding_days for t in closed) / len(closed), 1),
    }
