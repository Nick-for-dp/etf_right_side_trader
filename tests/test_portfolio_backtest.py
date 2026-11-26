"""组合回测核心回归测试。"""

from datetime import date

import pandas as pd

from src.backtest.ablation_config import (
    ADD_RULE_PROFIT_ONLY,
    ADD_RULE_PYRAMID_50,
    BUDGET_RULE_80_10_10_LADDER,
    BUDGET_RULE_80_20_PROFIT,
    AblationExperimentConfig,
    REENTRY_HIGH_VOL_COOLDOWN_20T,
    PortfolioRiskRuleConfig,
    REENTRY_PRICE_RECLAIM,
    REENTRY_SCORE_60,
    STOP_LOSS_ATR_2_0,
    STOP_LOSS_FIXED_8,
    STOP_LOSS_FIXED_10,
    STOP_LOSS_NONE,
)
from src.backtest.portfolio_backtest import (
    EquityPoint,
    PortfolioBacktest,
    PortfolioState,
    Position,
    TradeLog,
)
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
        position_limit=0.3,
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


def test_add_rule_profit_only_blocks_losing_add():
    days = ["2026-01-01", "2026-01-02"]
    bt = PortfolioBacktest(
        calendar=_Calendar(days),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=1.0,
        cooldown_days=0,
    )
    portfolio = PortfolioState(
        cash=100_000,
        positions={
            "AAA": Position(code="AAA", shares=1000, cost=1000, entry_date=date(2026, 1, 1)),
        },
    )
    trades = []
    stats = {}

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="加仓",
        exec_price=0.9,
        exec_date=date(2026, 1, 2),
        version="test",
        trades=trades,
        market_prices={"AAA": 0.9},
        experiment=AblationExperimentConfig(
            name="profit_only",
            label="盈利才加仓",
            add_rule=ADD_RULE_PROFIT_ONLY,
        ),
        signal_meta={"score": 80},
        stats=stats,
    )

    assert trades == []
    assert portfolio.positions["AAA"].shares == 1000
    assert stats["add_attempts"] == 1
    assert stats["add_rule_blocked"] == 1


def test_add_rule_pyramid_caps_add_shares_to_current_position_ratio():
    days = ["2026-01-01", "2026-01-02"]
    bt = PortfolioBacktest(
        calendar=_Calendar(days),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=1.0,
        cooldown_days=0,
    )
    portfolio = PortfolioState(
        cash=100_000,
        positions={
            "AAA": Position(code="AAA", shares=1000, cost=1000, entry_date=date(2026, 1, 1)),
        },
    )
    trades = []
    stats = {}

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="加仓",
        exec_price=1.2,
        exec_date=date(2026, 1, 2),
        version="test",
        trades=trades,
        market_prices={"AAA": 1.2},
        experiment=AblationExperimentConfig(
            name="pyramid_50",
            label="金字塔50%",
            add_rule=ADD_RULE_PYRAMID_50,
        ),
        signal_meta={"score": 80},
        stats=stats,
    )

    assert len(trades) == 1
    assert trades[0].shares == 500
    assert portfolio.positions["AAA"].shares == 1500
    assert stats["add_executed"] == 1
    assert stats["add_rule_scaled"] == 1


def test_entry_add_budget_rule_uses_entry_ratio_on_open():
    days = ["2026-01-01", "2026-01-02"]
    bt = PortfolioBacktest(
        calendar=_Calendar(days),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=0.3,
        cooldown_days=0,
    )
    portfolio = PortfolioState(cash=100_000)
    trades = []

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="建仓",
        exec_price=10.0,
        exec_date=date(2026, 1, 2),
        version="test",
        trades=trades,
        market_prices={"AAA": 10.0},
        experiment=AblationExperimentConfig(
            name="budget_80_20",
            label="80/20",
            entry_add_budget_rule=BUDGET_RULE_80_20_PROFIT,
        ),
        stats={},
    )

    pos = portfolio.positions["AAA"]
    assert len(trades) == 1
    assert trades[0].shares == 2400
    assert pos.target_budget == 30_000
    assert pos.used_budget == 24_000
    assert portfolio.cash == 76_000


def test_entry_add_budget_rule_uses_reserve_step_on_add():
    days = ["2026-01-01", "2026-01-02"]
    bt = PortfolioBacktest(
        calendar=_Calendar(days),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=1.0,
        cooldown_days=0,
    )
    portfolio = PortfolioState(
        cash=76_000,
        positions={
            "AAA": Position(
                code="AAA",
                shares=2400,
                cost=24_000,
                entry_date=date(2026, 1, 1),
                target_budget=30_000,
                used_budget=24_000,
            ),
        },
    )
    trades = []
    stats = {}

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="加仓",
        exec_price=12.0,
        exec_date=date(2026, 1, 2),
        version="test",
        trades=trades,
        market_prices={"AAA": 12.0},
        experiment=AblationExperimentConfig(
            name="budget_80_20",
            label="80/20",
            entry_add_budget_rule=BUDGET_RULE_80_20_PROFIT,
        ),
        signal_meta={"score": 80},
        stats=stats,
    )

    pos = portfolio.positions["AAA"]
    assert len(trades) == 1
    assert trades[0].shares == 500
    assert pos.shares == 2900
    assert pos.used_budget == 30_000
    assert pos.add_count == 1
    assert stats["add_executed"] == 1


def test_entry_add_budget_ladder_blocks_second_step_when_score_too_low():
    days = ["2026-01-01", "2026-01-02"]
    bt = PortfolioBacktest(
        calendar=_Calendar(days),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=0.3,
        cooldown_days=0,
    )
    portfolio = PortfolioState(
        cash=73_000,
        positions={
            "AAA": Position(
                code="AAA",
                shares=2700,
                cost=27_000,
                entry_date=date(2026, 1, 1),
                target_budget=30_000,
                used_budget=27_000,
                add_count=1,
            ),
        },
    )
    trades = []
    stats = {}

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="加仓",
        exec_price=12.0,
        exec_date=date(2026, 1, 2),
        version="test",
        trades=trades,
        market_prices={"AAA": 12.0},
        experiment=AblationExperimentConfig(
            name="budget_ladder",
            label="阶梯",
            entry_add_budget_rule=BUDGET_RULE_80_10_10_LADDER,
        ),
        signal_meta={"score": 65},
        stats=stats,
    )

    assert trades == []
    assert portfolio.positions["AAA"].add_count == 1
    assert stats["add_rule_blocked"] == 1


def test_fixed_stop_loss_rule_uses_configured_threshold():
    bt = PortfolioBacktest(calendar=_Calendar(["2026-01-01"]))
    portfolio = PortfolioState(
        cash=100_000,
        positions={
            "AAA": Position(code="AAA", shares=1000, cost=10_000, entry_date=date(2026, 1, 1)),
        },
    )

    no_signal = bt._check_risk(
        portfolio=portfolio,
        price_map={"AAA": {"2026-01-02": 9.05}},
        day_str="2026-01-02",
        experiment=AblationExperimentConfig(
            name="fixed10",
            label="固定-10%",
            stop_loss_rule=STOP_LOSS_FIXED_10,
        ),
    )
    signal = bt._check_risk(
        portfolio=portfolio,
        price_map={"AAA": {"2026-01-02": 8.95}},
        day_str="2026-01-02",
        experiment=AblationExperimentConfig(
            name="fixed10",
            label="固定-10%",
            stop_loss_rule=STOP_LOSS_FIXED_10,
        ),
    )

    assert no_signal == {}
    assert signal["AAA"]["source"] == "stop_loss"


def test_stop_loss_none_disables_stop_loss():
    bt = PortfolioBacktest(calendar=_Calendar(["2026-01-01"]))
    portfolio = PortfolioState(
        cash=100_000,
        positions={
            "AAA": Position(code="AAA", shares=1000, cost=10_000, entry_date=date(2026, 1, 1)),
        },
    )

    risk = bt._check_risk(
        portfolio=portfolio,
        price_map={"AAA": {"2026-01-02": 1.0}},
        day_str="2026-01-02",
        experiment=AblationExperimentConfig(
            name="none",
            label="不止损",
            use_stop_loss=False,
            stop_loss_rule=STOP_LOSS_NONE,
        ),
    )

    assert risk == {}


def test_atr_stop_loss_threshold_is_clamped():
    threshold_low_vol = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="atr",
            label="ATR",
            stop_loss_rule=STOP_LOSS_ATR_2_0,
        ),
        risk_info={"atr_pct": 0.01},
    )
    threshold_high_vol = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="atr",
            label="ATR",
            stop_loss_rule=STOP_LOSS_ATR_2_0,
        ),
        risk_info={"atr_pct": 0.10},
    )
    threshold_mid_vol = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="atr",
            label="ATR",
            stop_loss_rule=STOP_LOSS_ATR_2_0,
        ),
        risk_info={"atr_pct": 0.04},
    )

    assert threshold_low_vol == -0.06
    assert threshold_high_vol == -0.12
    assert threshold_mid_vol == -0.08


def test_config_stop_loss_profile_overrides_experiment_rule():
    threshold_none = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="profile",
            label="profile",
            stop_loss_rule=STOP_LOSS_FIXED_8,
            use_config_stop_loss_profiles=True,
        ),
        risk_info={"atr_pct": 0.04},
        stop_loss_profile="none",
    )
    threshold_atr = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="profile",
            label="profile",
            stop_loss_rule=STOP_LOSS_FIXED_8,
            use_config_stop_loss_profiles=True,
        ),
        risk_info={"atr_pct": 0.04},
        stop_loss_profile="atr_2_5",
    )

    assert threshold_none is None
    assert threshold_atr == -0.10


def test_reentry_rule_blocks_when_score_is_too_low():
    passed = PortfolioBacktest._reentry_rule_passed(
        rule=REENTRY_SCORE_60,
        advice={"signal_meta": {"score": 55}},
        current_price=10.0,
        indicator_info={},
        signal_date=date(2026, 1, 10),
        exit_info={"date": date(2026, 1, 1), "price": 9.5},
    )

    assert passed is False


def test_reentry_price_reclaim_requires_ma20_and_stop_price_buffer():
    blocked = PortfolioBacktest._reentry_rule_passed(
        rule=REENTRY_PRICE_RECLAIM,
        advice={"signal_meta": {"score": 70}},
        current_price=10.0,
        indicator_info={"ma20": 10.1, "atr_pct": 0.02},
        signal_date=date(2026, 1, 10),
        exit_info={"date": date(2026, 1, 1), "price": 9.9},
    )
    allowed = PortfolioBacktest._reentry_rule_passed(
        rule=REENTRY_PRICE_RECLAIM,
        advice={"signal_meta": {"score": 70}},
        current_price=10.2,
        indicator_info={"ma20": 10.0, "atr_pct": 0.02},
        signal_date=date(2026, 1, 10),
        exit_info={"date": date(2026, 1, 1), "price": 10.0},
    )

    assert blocked is False
    assert allowed is True


def test_baseline_reentry_allows_and_marks_entry():
    bt = PortfolioBacktest(calendar=_Calendar(["2026-01-01"]))
    advice = {"code": "AAA", "advice": "建仓", "signal_meta": {"score": 55}}
    stats = {}

    allowed = bt._reentry_allows_advice(
        advice=advice,
        current_prices={"AAA": 10.0},
        day_risk_data={"AAA": {"ma20": 9.8}},
        signal_date=date(2026, 1, 10),
        experiment=AblationExperimentConfig(name="base", label="base"),
        last_stop_loss_exits={"AAA": {"date": date(2026, 1, 1), "price": 9.5}},
        signal_day_index=5,
        stats=stats,
    )

    assert allowed is True
    assert advice["is_reentry_entry"] is True
    assert stats["reentry_attempts"] == 1
    assert stats["reentry_allowed"] == 1


def test_reentry_trading_day_cooldown_blocks_before_threshold():
    blocked = PortfolioBacktest._reentry_rule_passed(
        rule=REENTRY_HIGH_VOL_COOLDOWN_20T,
        advice={"signal_meta": {"score": 80}},
        current_price=10.0,
        indicator_info={},
        signal_date=date(2026, 2, 1),
        signal_day_index=19,
        exit_info={"date": date(2026, 1, 1), "price": 9.5, "trading_index": 0},
    )
    allowed = PortfolioBacktest._reentry_rule_passed(
        rule=REENTRY_HIGH_VOL_COOLDOWN_20T,
        advice={"signal_meta": {"score": 80}},
        current_price=10.0,
        indicator_info={},
        signal_date=date(2026, 2, 2),
        signal_day_index=20,
        exit_info={"date": date(2026, 1, 1), "price": 9.5, "trading_index": 0},
    )

    assert blocked is False
    assert allowed is True


def test_scoped_reentry_rule_ignores_non_target_volatility_group():
    bt = PortfolioBacktest(
        calendar=_Calendar(["2026-01-01"]),
        code_volatility_groups={"AAA": "low_vol"},
    )
    advice = {"code": "AAA", "advice": "建仓", "signal_meta": {"score": 80}}
    stats = {}

    allowed = bt._reentry_allows_advice(
        advice=advice,
        current_prices={"AAA": 10.0},
        day_risk_data={"AAA": {}},
        signal_date=date(2026, 2, 1),
        experiment=AblationExperimentConfig(
            name="high_vol_only",
            label="高波20T",
            reentry_rule=REENTRY_HIGH_VOL_COOLDOWN_20T,
        ),
        last_stop_loss_exits={"AAA": {"date": date(2026, 1, 1), "price": 9.5, "trading_index": 0}},
        signal_day_index=1,
        stats=stats,
    )

    assert allowed is True
    assert advice.get("is_reentry_entry") is None
    assert stats == {}


def test_portfolio_risk_rule_caps_total_exposure_buy_value():
    bt = PortfolioBacktest(
        calendar=_Calendar(["2026-01-01", "2026-01-02"]),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=1.0,
        cooldown_days=0,
    )
    portfolio = PortfolioState(
        cash=80_000,
        positions={"BBB": Position(code="BBB", shares=2000, cost=20_000, entry_date=date(2026, 1, 1))},
    )
    trades = []
    stats = {}

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="建仓",
        exec_price=10.0,
        exec_date=date(2026, 1, 2),
        version="risk",
        trades=trades,
        market_prices={"AAA": 10.0, "BBB": 10.0},
        experiment=AblationExperimentConfig(
            name="risk",
            label="risk",
            portfolio_risk_rule=PortfolioRiskRuleConfig(
                name="max_total_50",
                label="总仓50%",
                max_total_exposure=0.5,
            ),
        ),
        signal_meta={"score": 80},
        stats=stats,
    )

    assert len(trades) == 1
    assert trades[0].shares == 3000
    assert portfolio.cash == 50_000
    assert stats["portfolio_risk_scaled"] == 1
    assert stats["portfolio_risk_total_exposure_scaled"] == 1


def test_portfolio_risk_rule_blocks_new_high_vol_when_count_reached():
    bt = PortfolioBacktest(
        calendar=_Calendar(["2026-01-01", "2026-01-02"]),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=1.0,
        cooldown_days=0,
        code_volatility_groups={"AAA": "high_vol", "BBB": "high_vol"},
    )
    portfolio = PortfolioState(
        cash=80_000,
        positions={"BBB": Position(code="BBB", shares=2000, cost=20_000, entry_date=date(2026, 1, 1))},
    )
    trades = []
    stats = {}

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="建仓",
        exec_price=10.0,
        exec_date=date(2026, 1, 2),
        version="risk",
        trades=trades,
        market_prices={"AAA": 10.0, "BBB": 10.0},
        experiment=AblationExperimentConfig(
            name="risk",
            label="risk",
            portfolio_risk_rule=PortfolioRiskRuleConfig(
                name="max_high_count_1",
                label="高波最多1只",
                max_high_vol_positions=1,
            ),
        ),
        signal_meta={"score": 80},
        stats=stats,
    )

    assert trades == []
    assert "AAA" not in portfolio.positions
    assert stats["portfolio_risk_blocked"] == 1
    assert stats["portfolio_risk_high_vol_count_blocked"] == 1

def test_portfolio_risk_rule_blocks_when_single_position_cap_full():
    bt = PortfolioBacktest(
        calendar=_Calendar(["2026-01-01", "2026-01-02"]),
        initial_capital=100_000,
        cost_ratio=0.0,
        slippage=0.0,
        position_limit=1.0,
        cooldown_days=0,
    )
    portfolio = PortfolioState(
        cash=80_000,
        positions={"AAA": Position(code="AAA", shares=2000, cost=20_000, entry_date=date(2026, 1, 1))},
    )
    trades = []
    stats = {}

    bt._execute_advice(
        portfolio=portfolio,
        code="AAA",
        advice_action="加仓",
        exec_price=10.0,
        exec_date=date(2026, 1, 2),
        version="risk",
        trades=trades,
        market_prices={"AAA": 10.0},
        experiment=AblationExperimentConfig(
            name="risk",
            label="risk",
            portfolio_risk_rule=PortfolioRiskRuleConfig(
                name="single_20",
                label="单标20%",
                max_single_position_ratio=0.2,
            ),
        ),
        signal_meta={"score": 80},
        stats=stats,
    )

    assert trades == []
    assert portfolio.positions["AAA"].shares == 2000
    assert stats["portfolio_risk_blocked"] == 1
    assert stats["portfolio_risk_single_position_blocked"] == 1

