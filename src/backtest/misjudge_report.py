"""买入/卖出误判分析。

从回测引擎的交易记录中抽样复盘高亏损交易和被拦截交易，
区分策略信号问题、赔率门控问题、市场环境问题和执行问题。
"""

from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.backtest.portfolio_metrics import pair_closed_trades
from src.backtest.portfolio_backtest import run_portfolio_backtest
from src.database import indicators_repo, market_regime_repo, quote_repo, signals_repo
from src.service.calendar_service import TradingCalendarService
from src.utils import get_logger

logger = get_logger(__name__)


def run_misjudge_analysis(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    loss_threshold: float = -0.10,
) -> dict[str, Any]:
    """运行误判分析。

    Args:
        codes: ETF 代码列表
        start: 回测起始日期
        end:   结束日期
        loss_threshold: 亏损阈值（默认 -10%）

    Returns:
        {
            "loss_trades": [{code, date, pnl_pct, diagnosis, ...}],
            "summary": {亏损分布, 子信号归因, ...},
        }
    """
    from src.config import load_config
    config = load_config()

    if codes is None:
        codes = [e.symbol for e in config.etf_list]

    calendar = TradingCalendarService()
    if end is None:
        end_str = calendar.get_previous_trading_day()
        end = date.fromisoformat(end_str)
    if start is None:
        start = end - timedelta(days=config.lookback_days)

    # 运行净值回测获取交易记录（仅 v2.3 全门控版本）
    logger.info("运行净值回测获取交易记录...")
    result = run_portfolio_backtest(
        codes=codes, start=start, end=end,
        capital=100000,
    )
    full_gate = result["versions"].get("v2.3-full-gate") or result["versions"].get("v2.2", {})
    trades = full_gate.get("trades", [])

    loss_trades: list[dict] = []
    closed_trades = pair_closed_trades(trades)

    for t in closed_trades:
        pnl_pct = t["pnl_pct"]
        if pnl_pct <= loss_threshold:
            diagnosis = _diagnose_trade(
                t["code"], t["entry_date"], t["exit_date"],
                t["entry_price"], t["exit_price"],
            )
            loss_trades.append({
                "code": t["code"],
                "entry_date": str(t["entry_date"]),
                "exit_date": str(t["exit_date"]),
                "entry_price": round(t["entry_price"], 4),
                "exit_price": round(t["exit_price"], 4),
                "pnl_pct": round(pnl_pct, 4),
                "pnl_cash": round(t["pnl_cash"], 2),
                "diagnosis": diagnosis,
                "holding_days": t["holding_days"],
            })

    # 聚合分析
    categories = {"strategy": 0, "risk": 0, "execution": 0, "unknown": 0}
    for lt in loss_trades:
        cat = lt["diagnosis"].get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    summary = {
        "total_loss_trades": len(loss_trades),
        "total_all_trades": len(closed_trades),
        "loss_rate": len(loss_trades) / max(len(closed_trades), 1),
        "category_breakdown": categories,
        "avg_loss": (
            sum(lt["pnl_pct"] for lt in loss_trades) / len(loss_trades)
            if loss_trades else 0
        ),
    }

    return {"summary": summary, "loss_trades": loss_trades}


def _diagnose_trade(
    code: str, entry_date: date, exit_date: date,
    avg_price: float, exit_price: float,
) -> dict:
    """对单笔亏损交易进行四维诊断。"""
    diagnosis = {
        "category": "unknown",
        "signal_issue": None,
        "risk_issue": None,
        "execution_issue": None,
        "detail": "",
    }

    # 查入场前后的信号分解
    sigs = signals_repo.find_by_code_between(code, entry_date - timedelta(days=10), entry_date)
    entry_signal = None
    for s in reversed(sigs):
        if s.signal == "BUY":
            entry_signal = s
            break

    if entry_signal and entry_signal.signal_meta:
        meta = entry_signal.signal_meta
        s_trend = meta.get("s_trend", 0)
        s_macd = meta.get("s_macd", 0)
        s_rsi = meta.get("s_rsi", 0)
        s_bb = meta.get("s_bb", 0)
        score = meta.get("score", 0)

        # 检查哪个子信号方向错误
        wrong_signals = []
        if s_trend > 0 and exit_price < avg_price:
            wrong_signals.append("trend")
        if s_macd > 0 and exit_price < avg_price:
            wrong_signals.append("macd")
        if s_rsi > 0 and exit_price < avg_price:
            wrong_signals.append("rsi")
        if s_bb > 0 and exit_price < avg_price:
            wrong_signals.append("bb")

        # 检查入场后快速反转（3 日内跌幅 > 5%）
        quotes = quote_repo.find_by_code_in_range(code, entry_date, entry_date + timedelta(days=5))
        rapid_decline = False
        for q in quotes:
            if q.date > entry_date:
                decline = (float(q.close) - avg_price) / avg_price
                if decline <= -0.05:
                    rapid_decline = True
                    break

        detail_parts = []
        if wrong_signals:
            diagnosis["category"] = "strategy"
            diagnosis["signal_issue"] = f"子信号方向错误: {', '.join(wrong_signals)}"
            detail_parts.append(f"入场 score={score:.1f}")
            detail_parts.append(f"trend={s_trend:+.2f} macd={s_macd:+.2f} rsi={s_rsi:+.2f} bb={s_bb:+.2f}")
        if rapid_decline:
            diagnosis["category"] = "execution"
            diagnosis["execution_issue"] = "入场 3 日内快速下跌 > 5%"
            detail_parts.append("入场后快速反转")
        if not wrong_signals and not rapid_decline:
            diagnosis["category"] = "risk"
            diagnosis["risk_issue"] = "趋势延续后反转，风控不足"

        diagnosis["detail"] = " | ".join(detail_parts)

    return diagnosis


def format_misjudge_report(result: dict[str, Any]) -> str:
    """格式化为可读的误判分析报告。"""
    lines = []
    lines.append("=" * 72)
    lines.append("  买卖误判分析报告")
    lines.append("=" * 72)

    s = result["summary"]
    lines.append(f"  总亏损交易: {s['total_loss_trades']}")
    lines.append(f"  总平仓交易: {s['total_all_trades']}")
    lines.append(f"  亏损率: {s['loss_rate']:.1%}")
    lines.append(f"  平均亏损: {s['avg_loss']:.2%}")
    lines.append("")

    lines.append("【问题分类】")
    for cat, count in sorted(s["category_breakdown"].items()):
        lines.append(f"  {cat}: {count} ({count/max(s['total_loss_trades'],1):.0%})")

    lines.append("")
    lines.append("-" * 72)
    lines.append("【亏损交易明细（前 30 条）】")
    lines.append(f"  {'代码':>6s}  {'入场日':>10s}  {'出场日':>10s}  {'盈亏':>8s}  {'持有':>5s}  {'分类':>10s}  {'诊断'}")
    for lt in result["loss_trades"][:30]:
        diag = lt["diagnosis"]
        lines.append(
            f"  {lt['code']:>6s}  {lt['entry_date']:>10s}  {lt['exit_date']:>10s}"
            f"  {lt['pnl_pct']:>8.2%}  {lt['holding_days']:>4d}d"
            f"  {diag.get('category', '?'):>10s}  {diag.get('detail', '')}"
        )

    return "\n".join(lines)
