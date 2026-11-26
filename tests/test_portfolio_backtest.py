"""组合回测核心回归测试（生产唯一版本 v2.5 limited）。"""

from datetime import date

import pandas as pd

from src.backtest.portfolio_backtest import (
    EquityPoint,
    PortfolioBacktest,
    PortfolioState,
    Position,
    TradeLog,
)
from src.backtest.portfolio_metrics import calculate_metrics, pair_closed_trades
from src.risk import RiskController, ProfileStopLossRule

_BUDGET = {
    "entry_ratio": 0.7,
    "add_steps": [
        {"ratio": 0.15, "require_profit": True, "min_score": 60},
        {"ratio": 0.15, "require_profit": True, "min_score": 70},
    ],
}


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


class _Config:
    risk_rules = [
        {"type": "max_holding_days", "params": {"days": 90}},
        {"type": "profile_stop_loss", "params": {"default_profile": "fixed_8"}},
    ]


def _bt(days: list[str] | None = None, **kwargs) -> PortfolioBacktest:
    return PortfolioBacktest(
        calendar=_Calendar(days or ["2026-01-01", "2026-01-02"]),
        initial_capital=kwargs.pop("initial_capital", 100_000),
        cost_ratio=kwargs.pop("cost_ratio", 0.0),
        slippage=kwargs.pop("slippage", 0.0),
        position_limit=kwargs.pop("position_limit", 0.3),
        cooldown_days=kwargs.pop("cooldown_days", 0),
        entry_add_budget=kwargs.pop("entry_add_budget", _BUDGET),
        risk_controller=RiskController(_Config()),
        **kwargs,
    )


def _signals() -> pd.DataFrame:
    return pd.DataFrame([
        {"code": "AAA", "date": "2026-01-01", "signal": "BUY", "signal_meta": {}},
        {"code": "AAA", "date": "2026-01-03", "signal": "SELL", "signal_meta": {}},
    ])


def test_portfolio_backtest_keeps_equity_curve_chronological():
    """交易日推进必须按时间升序，避免资金曲线折返。"""
    days = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    bt = _bt(days)

    equity_curve, trades, _stats = bt._run(
        signal_df=_signals(),
        codes=["AAA"],
        price_map={"AAA": {
            "2026-01-01": 10.0,
            "2026-01-02": 10.0,
            "2026-01-03": 11.0,
            "2026-01-04": 12.0,
        }},
        atr_map={"AAA": {}},
        trading_days=days,
        trading_day_set=set(days),
        regime_by_day={},
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


def test_open_position_buys_entry_ratio_of_target_budget():
    """建仓只投 70% 目标预算，剩余留给两个 15% 加仓阶梯。"""
    bt = _bt(["2026-01-01", "2026-01-02"])
    portfolio = PortfolioState(cash=100_000)
    trades = []

    bt._execute_advice(
        portfolio=portfolio, code="AAA", action="建仓",
        exec_price=10.0, exec_date=date(2026, 1, 2),
        trades=trades, market_prices={"AAA": 10.0}, stats={},
    )

    pos = portfolio.positions["AAA"]
    assert len(trades) == 1
    assert trades[0].shares == 2100          # 30k × 0.7 / 10
    assert pos.target_budget == 30_000
    assert pos.used_budget == 21_000
    assert portfolio.cash == 79_000


def test_add_step_uses_reserve_ratio():
    """第一次加仓投目标预算的 15%。"""
    bt = _bt(["2026-01-01", "2026-01-02"])
    portfolio = PortfolioState(
        cash=79_000,
        positions={"AAA": Position(
            code="AAA", shares=2100, cost=21_000,
            entry_date=date(2026, 1, 1), target_budget=30_000, used_budget=21_000,
        )},
    )
    trades, stats = [], {}

    bt._execute_advice(
        portfolio=portfolio, code="AAA", action="加仓",
        exec_price=12.0, exec_date=date(2026, 1, 2),
        trades=trades, market_prices={"AAA": 12.0},
        signal_meta={"score": 80}, stats=stats,
    )

    pos = portfolio.positions["AAA"]
    assert len(trades) == 1
    assert trades[0].shares == 300           # 4500 / 12 → 375 → 300 整手
    assert pos.shares == 2400
    assert pos.add_count == 1
    assert stats["add_executed"] == 1


def test_add_blocked_when_not_profitable():
    """require_profit 的阶梯在浮亏时不允许加仓。"""
    bt = _bt()
    portfolio = PortfolioState(
        cash=100_000,
        positions={"AAA": Position(
            code="AAA", shares=1000, cost=1000,
            entry_date=date(2026, 1, 1), target_budget=30_000, used_budget=1000,
        )},
    )
    trades, stats = [], {}

    bt._execute_advice(
        portfolio=portfolio, code="AAA", action="加仓",
        exec_price=0.9, exec_date=date(2026, 1, 2),
        trades=trades, market_prices={"AAA": 0.9},
        signal_meta={"score": 80}, stats=stats,
    )

    assert trades == []
    assert portfolio.positions["AAA"].shares == 1000
    assert stats["add_attempts"] == 1
    assert stats["add_rule_blocked"] == 1


def test_second_add_step_blocks_low_score():
    """第二步加仓要求 score ≥ 70。"""
    bt = _bt()
    portfolio = PortfolioState(
        cash=73_000,
        positions={"AAA": Position(
            code="AAA", shares=2700, cost=27_000,
            entry_date=date(2026, 1, 1), target_budget=30_000,
            used_budget=27_000, add_count=1,
        )},
    )
    trades, stats = [], {}

    bt._execute_advice(
        portfolio=portfolio, code="AAA", action="加仓",
        exec_price=12.0, exec_date=date(2026, 1, 2),
        trades=trades, market_prices={"AAA": 12.0},
        signal_meta={"score": 65}, stats=stats,
    )

    assert trades == []
    assert portfolio.positions["AAA"].add_count == 1
    assert stats["add_rule_blocked"] == 1


def test_fixed_stop_loss_profile_triggers():
    """fixed_8 profile 在 -8% 触发止损。"""
    bt = _bt(["2026-01-01"])
    portfolio = PortfolioState(
        cash=100_000,
        positions={"AAA": Position(
            code="AAA", shares=1000, cost=10_000, entry_date=date(2026, 1, 1),
        )},
    )
    bt.code_stop_loss_profiles = {"AAA": "fixed_8"}

    no_signal = bt._check_risk(
        portfolio, {"AAA": {"2026-01-02": 9.25}}, {"AAA": {}},
        "2026-01-02", date(2026, 1, 2),
    )
    signal = bt._check_risk(
        portfolio, {"AAA": {"2026-01-02": 9.15}}, {"AAA": {}},
        "2026-01-02", date(2026, 1, 2),
    )

    assert no_signal == {}
    assert signal["AAA"]["source"] == "stop_loss"


def test_stop_loss_profile_none_disables_rule():
    bt = _bt(["2026-01-01"])
    portfolio = PortfolioState(
        cash=100_000,
        positions={"AAA": Position(
            code="AAA", shares=1000, cost=10_000, entry_date=date(2026, 1, 1),
        )},
    )
    bt.code_stop_loss_profiles = {"AAA": "none"}

    risk = bt._check_risk(
        portfolio, {"AAA": {"2026-01-02": 1.0}}, {"AAA": {}},
        "2026-01-02", date(2026, 1, 2),
    )
    assert risk == {}


def test_max_holding_days_forces_exit():
    bt = _bt(["2026-01-01"])
    portfolio = PortfolioState(
        cash=100_000,
        positions={"AAA": Position(
            code="AAA", shares=1000, cost=10_000, entry_date=date(2026, 1, 1),
        )},
    )

    risk = bt._check_risk(
        portfolio, {"AAA": {"2026-04-01": 10.0}}, {"AAA": {}},
        "2026-04-01", date(2026, 4, 1),
    )
    assert risk["AAA"]["source"] == "max_holding"


def test_atr_stop_loss_threshold_is_clamped():
    low = ProfileStopLossRule.threshold("atr_2_0", {"atr_pct": 0.01})
    high = ProfileStopLossRule.threshold("atr_2_0", {"atr_pct": 0.10})
    mid = ProfileStopLossRule.threshold("atr_2_0", {"atr_pct": 0.04})

    assert low == -0.06
    assert high == -0.12
    assert mid == -0.08


def test_atr_profile_uses_configured_multiplier():
    assert ProfileStopLossRule.threshold("atr_2_5", {"atr_pct": 0.04}) == -0.10
    assert ProfileStopLossRule.threshold("none", {"atr_pct": 0.04}) is None


def test_reentry_marks_entry_after_stop_loss_exit():
    bt = _bt(["2026-01-01"])
    advice = {"code": "AAA", "advice": "建仓", "signal_meta": {"score": 55}}
    stats = {"reentry_attempts": 0, "reentry_allowed": 0}

    bt._mark_reentry(
        advice,
        {"AAA": {"date": date(2026, 1, 1), "price": 9.5}},
        stats,
    )

    assert advice["is_reentry_entry"] is True
    assert stats["reentry_attempts"] == 1
    assert stats["reentry_allowed"] == 1
