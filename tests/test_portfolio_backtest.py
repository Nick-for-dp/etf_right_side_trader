"""组合回测核心回归测试。"""

from datetime import date

import pandas as pd

from src.backtest.portfolio_backtest import EquityPoint, PortfolioBacktest, TradeLog
from src.backtest.portfolio_metrics import calculate_metrics, pair_closed_trades


class _Calendar:
    def __init__(self, days: list[str]):
        self.days = days

    def get_next_trading_day(self, day: str) -> str | None:
        try:
            idx = self.days.index(day)
        except ValueError:
            return None
        next_idx = idx + 1
        return self.days[next_idx] if next_idx < len(self.days) else None


def _signals() -> pd.DataFrame:
    return pd.DataFrame([
        {"code": "AAA", "date": "2026-01-01", "signal": "BUY", "signal_meta": {}},
        {"code": "AAA", "date": "2026-01-03", "signal": "SELL", "signal_meta": {}},
    ])


def test_portfolio_backtest_keeps_equity_curve_chronological():
    """交易日推进必须按时间升序，避免资金曲线折返。"""
    days = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    bt = PortfolioBacktest(
        calendar=_Calendar(days),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=1.0,
        cooldown_days=0,
    )

    equity_curve, trades, _stats = bt._run_advisor_config(
        version="test",
        signal_df=_signals(),
        codes=["AAA"],
        price_map={
            "AAA": {
                "2026-01-01": 10.0,
                "2026-01-02": 10.0,
                "2026-01-03": 11.0,
                "2026-01-04": 12.0,
            }
        },
        odds_map=None,
        market_regime_map=None,
        trading_days=days,
        trading_day_set=set(days),
    )

    assert [str(e.date) for e in equity_curve] == days
    assert [str(t.date) for t in trades] == ["2026-01-02", "2026-01-04"]


def test_pair_closed_trades_isolated_by_code():
    """多 ETF 交易配对必须按代码隔离，不能跨代码平均成本。"""
    trades = [
        TradeLog("AAA", date(2026, 1, 2), "建仓", 10.0, 100, 0.0, 10_000, 9_000, "v"),
        TradeLog("BBB", date(2026, 1, 2), "建仓", 20.0, 100, 0.0, 9_000, 7_000, "v"),
        TradeLog("AAA", date(2026, 1, 3), "SELL", 11.0, 100, 0.0, 7_000, 8_100, "v"),
        TradeLog("BBB", date(2026, 1, 4), "SELL", 18.0, 100, 0.0, 8_100, 9_900, "v"),
    ]

    closed = pair_closed_trades(trades)
    assert [(t["code"], round(t["pnl_pct"], 4)) for t in closed] == [
        ("AAA", 0.1),
        ("BBB", -0.1),
    ]

    metrics = calculate_metrics(
        [
            EquityPoint(date(2026, 1, 1), 10_000, 0, 10_000, "v"),
            EquityPoint(date(2026, 1, 2), 7_000, 3_000, 10_000, "v"),
            EquityPoint(date(2026, 1, 3), 8_100, 1_800, 9_900, "v"),
            EquityPoint(date(2026, 1, 4), 9_900, 0, 9_900, "v"),
        ],
        trades,
        initial_capital=10_000,
    )
    assert metrics["win_rate"] == "50.00%"
    assert metrics["profit_factor"] == "0.5000"
