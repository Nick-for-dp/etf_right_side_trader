"""回测业绩指标计算。

从权益曲线和交易日志计算标准组合指标。
"""

from typing import Any

import numpy as np

from .portfolio_backtest import EquityPoint, TradeLog


def calculate_metrics(
    equity_curve: list[EquityPoint],
    trades: list[TradeLog],
    initial_capital: float,
) -> dict[str, Any]:
    """计算回测业绩指标。

    Args:
        equity_curve: 每日净值点列表
        trades: 成交记录列表
        initial_capital: 初始资金

    Returns:
        包含以下字段的字典（值均为字符串，保留 4 位有效数字）：
        - annual_return: 年化收益率
        - max_drawdown: 最大回撤
        - calmar: Calmar 比率
        - sharpe: Sharpe 比率
        - win_rate: 胜率
        - profit_factor: 利润因子
        - total_trades: 总交易次数
        - turnover: 年化换手率
        - avg_holding_days: 平均持有天数
    """
    if not equity_curve:
        return _empty_metrics()

    # ── 权益曲线 → 日收益率序列 ──
    ordered_curve = sorted(equity_curve, key=lambda e: e.date)
    values = [e.total_equity for e in ordered_curve]

    equity_series = np.array(values, dtype=float)
    daily_returns = np.diff(equity_series) / equity_series[:-1]

    if len(daily_returns) == 0:
        return _empty_metrics()

    # ── 交易日数 → 年化系数 ──
    n_days = len(daily_returns)
    ann_factor = 252 / n_days if n_days > 0 else 1.0

    # ── 年化收益 ──
    total_return = (equity_series[-1] - initial_capital) / initial_capital
    annual_return = (1 + total_return) ** ann_factor - 1.0

    # ── 最大回撤（净值口径） ──
    peak = np.maximum.accumulate(equity_series)
    drawdowns = (peak - equity_series) / peak
    max_drawdown = float(np.max(drawdowns))

    # ── Calmar ──
    calmar = annual_return / max_drawdown if max_drawdown > 0 else 0.0

    # ── Sharpe（无风险利率 = 0） ──
    if len(daily_returns) > 1 and np.std(daily_returns, ddof=1) > 0:
        sharpe = np.mean(daily_returns) / np.std(daily_returns, ddof=1) * np.sqrt(252)
    else:
        sharpe = 0.0

    # ── 交易统计 ──
    closed_trades = pair_closed_trades(trades)
    total_trades = len(closed_trades)

    win_count = sum(1 for p in closed_trades if p["pnl_cash"] > 0)
    win_rate = win_count / total_trades if total_trades else 0.0

    total_gain = sum(p["pnl_cash"] for p in closed_trades if p["pnl_cash"] > 0)
    total_loss = abs(sum(p["pnl_cash"] for p in closed_trades if p["pnl_cash"] < 0))
    profit_factor = total_gain / total_loss if total_loss > 0 else float("inf")

    # ── 年化换手率 ──
    total_turnover = sum(t.shares * t.price for t in trades) / initial_capital
    turnover = total_turnover * ann_factor

    # ── 平均持有天数 ──
    avg_holding_days = (
        sum(p["holding_days"] for p in closed_trades) / total_trades
        if total_trades > 0 else 0
    )

    def _fmt(v: float, is_pct: bool = False) -> str:
        if np.isnan(v) or np.isinf(v):
            return "N/A"
        if is_pct:
            return f"{v:.2%}"
        return f"{v:.4f}"

    return {
        "annual_return": _fmt(annual_return, is_pct=True),
        "max_drawdown": _fmt(max_drawdown, is_pct=True),
        "calmar": _fmt(calmar),
        "sharpe": _fmt(sharpe),
        "win_rate": _fmt(win_rate, is_pct=True),
        "profit_factor": _fmt(profit_factor),
        "total_trades": str(total_trades),
        "turnover": _fmt(turnover, is_pct=True),
        "avg_holding_days": f"{avg_holding_days:.1f}",
        # 原始值（供后续分析使用）
        "_total_return": total_return,
        "_max_dd": max_drawdown,
        "_daily_returns_len": n_days,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "annual_return": "N/A",
        "max_drawdown": "N/A",
        "calmar": "N/A",
        "sharpe": "N/A",
        "win_rate": "N/A",
        "profit_factor": "N/A",
        "total_trades": "0",
        "turnover": "N/A",
        "avg_holding_days": "N/A",
    }


def pair_closed_trades(trades: list[TradeLog]) -> list[dict[str, Any]]:
    """按 ETF 代码将 BUY/ADD 与后续 SELL 配对。

    TradeLog 的 cash_before/cash_after 已包含滑点和佣金影响，用现金流计算
    盈亏比直接用价格更接近真实账户口径。
    """
    buy_queue: dict[str, list[TradeLog]] = {}
    closed: list[dict[str, Any]] = []

    ordered_trades = sorted(trades, key=lambda t: (t.date, t.code, _action_order(t.action)))
    for trade in ordered_trades:
        if trade.action in ("BUY", "建仓", "加仓"):
            buy_queue.setdefault(trade.code, []).append(trade)
            continue

        if trade.action != "SELL":
            continue

        buys = buy_queue.get(trade.code, [])
        if not buys:
            continue

        total_shares = sum(b.shares for b in buys)
        if total_shares <= 0:
            buy_queue[trade.code] = []
            continue

        cash_outflow = sum(b.cash_before - b.cash_after for b in buys)
        cash_inflow = trade.cash_after - trade.cash_before
        if cash_outflow <= 0:
            buy_queue[trade.code] = []
            continue

        avg_entry_price = sum(b.price * b.shares for b in buys) / total_shares
        entry_date = min(b.date for b in buys)
        pnl_cash = cash_inflow - cash_outflow
        closed.append({
            "code": trade.code,
            "entry_date": entry_date,
            "exit_date": trade.date,
            "entry_price": avg_entry_price,
            "exit_price": trade.price,
            "shares": total_shares,
            "cash_outflow": cash_outflow,
            "cash_inflow": cash_inflow,
            "pnl_cash": pnl_cash,
            "pnl_pct": pnl_cash / cash_outflow,
            "holding_days": (trade.date - entry_date).days,
        })
        buy_queue[trade.code] = []

    return closed


def open_positions_from_trades(trades: list[TradeLog]) -> list[dict[str, Any]]:
    """从交易日志推导仍未平仓的回测持仓。"""
    buy_queue: dict[str, list[TradeLog]] = {}
    ordered_trades = sorted(trades, key=lambda t: (t.date, t.code, _action_order(t.action)))

    for trade in ordered_trades:
        if trade.action in ("BUY", "建仓", "加仓"):
            buy_queue.setdefault(trade.code, []).append(trade)
        elif trade.action == "SELL":
            buy_queue[trade.code] = []

    positions: list[dict[str, Any]] = []
    for code, buys in buy_queue.items():
        if not buys:
            continue
        total_shares = sum(b.shares for b in buys)
        cash_outflow = sum(b.cash_before - b.cash_after for b in buys)
        if total_shares <= 0:
            continue
        positions.append({
            "code": code,
            "entry_date": min(b.date for b in buys),
            "entry_price": sum(b.price * b.shares for b in buys) / total_shares,
            "shares": total_shares,
            "cash_outflow": cash_outflow,
        })
    return positions


def _action_order(action: str) -> int:
    if action == "SELL":
        return 1
    return 0
