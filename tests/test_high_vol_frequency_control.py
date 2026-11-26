"""High-vol frequency-control experiment tests."""

from src.backtest.ablation_config import (
    HIGH_VOL_ADD_INTERVAL_10,
    HIGH_VOL_BUY_CONFIRM_2,
    HIGH_VOL_MAX_POS_6,
    HIGH_VOL_STOP12,
    AblationExperimentConfig,
    high_vol_frequency_combo_experiments,
    high_vol_frequency_single_experiments,
)
from src.backtest.high_vol_frequency_control_report import (
    format_high_vol_frequency_control_report,
)
from src.backtest.portfolio_backtest import (
    PortfolioBacktest,
    PortfolioState,
    Position,
)
from src.models import SignalType


class _Calendar:
    def get_next_trading_day(self, day: str):
        return None


def test_high_vol_frequency_matrices_include_baseline_mixed_and_candidates():
    single = high_vol_frequency_single_experiments()
    combo = high_vol_frequency_combo_experiments()

    assert single[0].name == "baseline_v2_4_segment_stop"
    assert single[1].name == "mixed_high_vol_signal"
    assert {exp.high_vol_frequency_rule.name for exp in single[2:]} == {
        "high_vol_stop12",
        "high_vol_buy_confirm_2",
        "high_vol_buy_confirm_3",
        "high_vol_add_interval_10",
        "high_vol_sell_confirm_2",
        "high_vol_sell_confirm_3",
        "high_vol_min_hold_5",
        "high_vol_min_hold_10",
        "high_vol_max_pos_6",
    }
    assert {exp.high_vol_frequency_rule.name for exp in combo[2:]} == {
        "high_vol_buy2_add10",
        "high_vol_buy2_sell2",
        "high_vol_buy2_hold5_add10",
        "high_vol_buy2_max6",
    }


def test_high_vol_stop12_overrides_profile_threshold_only_when_rule_is_present():
    baseline = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="base",
            label="base",
            use_config_stop_loss_profiles=True,
        ),
        risk_info={"atr_pct": 0.04},
        stop_loss_profile="atr_2_5",
    )
    high_vol_override = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="stop12",
            label="stop12",
            use_config_stop_loss_profiles=True,
        ),
        risk_info={"atr_pct": 0.04},
        stop_loss_profile="atr_2_5",
        high_vol_frequency_rule=HIGH_VOL_STOP12,
    )

    assert baseline == -0.10
    assert high_vol_override == -0.12


def test_buy_confirm_blocks_first_high_vol_buy_signal():
    bt = PortfolioBacktest(
        calendar=_Calendar(),
        code_volatility_groups={"AAA": "high_vol", "BBB": "low_vol"},
    )
    experiment = AblationExperimentConfig(
        name="buy2",
        label="BUY2",
        high_vol_frequency_rule=HIGH_VOL_BUY_CONFIRM_2,
    )
    stats = {}
    buy_streaks = {}
    sell_streaks = {}

    first = bt._apply_high_vol_frequency_signal_filter(
        signal_rows=[
            {"code": "AAA", "date": "2026-01-01", "signal": SignalType.BUY.value, "signal_meta": {}},
            {"code": "BBB", "date": "2026-01-01", "signal": SignalType.BUY.value, "signal_meta": {}},
        ],
        portfolio=PortfolioState(cash=100_000),
        day_index=0,
        experiment=experiment,
        buy_streak_by_code=buy_streaks,
        sell_streak_by_code=sell_streaks,
        stats=stats,
    )
    second = bt._apply_high_vol_frequency_signal_filter(
        signal_rows=[
            {"code": "AAA", "date": "2026-01-02", "signal": SignalType.BUY.value, "signal_meta": {}},
        ],
        portfolio=PortfolioState(cash=100_000),
        day_index=1,
        experiment=experiment,
        buy_streak_by_code=buy_streaks,
        sell_streak_by_code=sell_streaks,
        stats=stats,
    )

    assert first[0]["signal"] == SignalType.HOLD.value
    assert first[1]["signal"] == SignalType.BUY.value
    assert second[0]["signal"] == SignalType.BUY.value
    assert stats["freq_buy_blocked"] == 1


def test_add_interval_blocks_high_vol_add_before_threshold():
    bt = PortfolioBacktest(
        calendar=_Calendar(),
        code_volatility_groups={"AAA": "high_vol"},
    )
    experiment = AblationExperimentConfig(
        name="add10",
        label="加仓10T",
        high_vol_frequency_rule=HIGH_VOL_ADD_INTERVAL_10,
    )
    portfolio = PortfolioState(
        cash=100_000,
        positions={
            "AAA": Position(
                code="AAA",
                shares=1000,
                cost=10_000,
                entry_trading_index=0,
                last_add_trading_index=3,
            )
        },
    )
    stats = {}

    allowed, _planned = bt._high_vol_frequency_allows_advice(
        advice={"code": "AAA", "advice": "加仓"},
        portfolio=portfolio,
        day_index=8,
        experiment=experiment,
        planned_high_vol_entries=0,
        stats=stats,
    )

    assert allowed is False
    assert stats["freq_add_interval_blocked"] == 1


def test_max_high_vol_positions_blocks_extra_entry():
    bt = PortfolioBacktest(
        calendar=_Calendar(),
        code_volatility_groups={f"A{i}": "high_vol" for i in range(7)},
    )
    experiment = AblationExperimentConfig(
        name="max6",
        label="最多6",
        high_vol_frequency_rule=HIGH_VOL_MAX_POS_6,
    )
    portfolio = PortfolioState(
        cash=100_000,
        positions={
            f"A{i}": Position(code=f"A{i}", shares=100, cost=1000)
            for i in range(6)
        },
    )
    stats = {}

    allowed, _planned = bt._high_vol_frequency_allows_advice(
        advice={"code": "A6", "advice": "建仓"},
        portfolio=portfolio,
        day_index=10,
        experiment=experiment,
        planned_high_vol_entries=0,
        stats=stats,
    )

    assert allowed is False
    assert stats["freq_max_positions_blocked"] == 1


def test_format_high_vol_frequency_control_report_shows_reduction_and_blocks():
    baseline = {
        "summary": {
            "annual_return": "10.00%",
            "max_drawdown": "20.00%",
            "calmar": "0.5000",
            "sharpe": "0.6000",
            "win_rate": "50.00%",
            "profit_factor": "1.5000",
            "total_trades": "100",
        },
        "stats": {},
        "experiment": {"label": "baseline-v2.4"},
    }
    mixed = {
        "summary": {
            "annual_return": "15.00%",
            "max_drawdown": "22.00%",
            "calmar": "0.6818",
            "sharpe": "0.8000",
            "win_rate": "42.00%",
            "profit_factor": "1.8000",
            "total_trades": "150",
        },
        "stats": {},
        "experiment": {"label": "高波新信号混合"},
    }
    candidate = {
        "summary": {
            "annual_return": "14.00%",
            "max_drawdown": "18.00%",
            "calmar": "0.7778",
            "sharpe": "0.7900",
            "win_rate": "45.00%",
            "profit_factor": "1.7000",
            "total_trades": "120",
        },
        "stats": {"freq_buy_blocked": 12, "freq_add_interval_blocked": 4},
        "experiment": {"label": "BUY2+加仓10T"},
    }
    result = {
        "meta": {
            "codes": ["AAA"],
            "high_vol_codes": ["AAA"],
            "low_vol_codes": [],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
        },
        "layers": [
            {
                "key": "combo",
                "label": "组合候选",
                "windows": [
                    {
                        "meta": {
                            "window": "2016-2026",
                            "start": "2016-01-01",
                            "end": "2026-06-03",
                            "baseline_name": "baseline_v2_4_segment_stop",
                            "mixed_name": "mixed_high_vol_signal",
                        },
                        "versions": {
                            "baseline_v2_4_segment_stop": baseline,
                            "mixed_high_vol_signal": mixed,
                            "high_vol_buy2_add10": candidate,
                        },
                    }
                ],
            }
        ],
    }

    report = format_high_vol_frequency_control_report(result)

    assert "高波新信号交易频率控制实验报告" in report
    assert "组合候选" in report
    assert "BUY2+加仓10T" in report
    assert "+30" in report
    assert "BUY拦" in report
