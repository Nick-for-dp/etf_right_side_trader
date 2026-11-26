"""High-vol trade-quality control experiment tests."""

from src.backtest.ablation_config import (
    HIGH_VOL_QUALITY_BUDGET_TIER,
    HIGH_VOL_QUALITY_COMPOSITE,
    HIGH_VOL_QUALITY_DAILY_TOP2,
    HIGH_VOL_QUALITY_SCORE55,
    AblationExperimentConfig,
    high_vol_quality_combo_experiments,
    high_vol_quality_single_experiments,
)
from src.backtest.high_vol_quality_control_report import (
    format_high_vol_quality_control_report,
)
from src.backtest.portfolio_backtest import PortfolioBacktest


class _Calendar:
    def get_next_trading_day(self, day: str):
        return None


def test_high_vol_quality_matrices_include_baseline_mixed_and_candidates():
    single = high_vol_quality_single_experiments()
    combo = high_vol_quality_combo_experiments()

    assert single[0].name == "baseline_v2_4_segment_stop"
    assert single[1].name == "mixed_high_vol_signal"
    assert single[2].name == "high_vol_stop12_reference"
    assert {exp.high_vol_quality_rule.name for exp in single[3:]} == {
        "high_vol_quality_score55",
        "high_vol_quality_momentum",
        "high_vol_quality_daily_top2",
        "high_vol_quality_budget_tier",
        "high_vol_quality_add_strict",
    }
    assert {exp.high_vol_quality_rule.name for exp in combo[2:]} == {
        "high_vol_quality_score55_top2",
        "high_vol_quality_score55_budget",
        "high_vol_quality_composite",
    }


def test_high_vol_quality_entry_filter_only_affects_high_vol_entries():
    bt = PortfolioBacktest(
        calendar=_Calendar(),
        code_volatility_groups={"AAA": "high_vol", "BBB": "low_vol"},
    )
    experiment = AblationExperimentConfig(
        name="score55",
        label="BUY分>=55",
        high_vol_quality_rule=HIGH_VOL_QUALITY_SCORE55,
    )
    stats = {}

    blocked = bt._high_vol_quality_allows_entry(
        {
            "code": "AAA",
            "advice": "建仓",
            "signal_meta": {"score": 54.9, "s_macd": 0.2, "s_rsi": 0.1},
        },
        experiment,
        stats,
    )
    low_vol_allowed = bt._high_vol_quality_allows_entry(
        {
            "code": "BBB",
            "advice": "建仓",
            "signal_meta": {"score": 10.0},
        },
        experiment,
        stats,
    )

    assert blocked is False
    assert low_vol_allowed is True
    assert stats["quality_entry_candidates"] == 1
    assert stats["quality_entry_blocked"] == 1


def test_high_vol_quality_daily_limit_keeps_top_score_entries():
    bt = PortfolioBacktest(
        calendar=_Calendar(),
        code_volatility_groups={"AAA": "high_vol", "BBB": "high_vol", "CCC": "high_vol", "DDD": "low_vol"},
    )
    experiment = AblationExperimentConfig(
        name="top2",
        label="每日前2",
        high_vol_quality_rule=HIGH_VOL_QUALITY_DAILY_TOP2,
    )
    stats = {}
    advices = [
        {"code": "AAA", "advice": "建仓", "signal_meta": {"score": 60.0}},
        {"code": "BBB", "advice": "建仓", "signal_meta": {"score": 70.0}},
        {"code": "CCC", "advice": "建仓", "signal_meta": {"score": 65.0}},
        {"code": "DDD", "advice": "建仓", "signal_meta": {"score": 20.0}},
        {"code": "AAA", "advice": "卖出", "signal_meta": {"score": 1.0}},
    ]

    filtered = bt._apply_high_vol_quality_daily_limit(advices, experiment, stats)

    assert [adv["code"] for adv in filtered] == ["BBB", "CCC", "DDD", "AAA"]
    assert stats["quality_daily_limit_blocked"] == 1


def test_high_vol_quality_budget_tier_scales_target_budget():
    bt = PortfolioBacktest(
        calendar=_Calendar(),
        code_volatility_groups={"AAA": "high_vol", "BBB": "low_vol"},
    )
    experiment = AblationExperimentConfig(
        name="budget",
        label="质量分层仓位",
        high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
    )

    weak = bt._position_target_budget(
        30_000.0,
        experiment,
        code="AAA",
        signal_meta={"score": 52.0},
    )
    medium = bt._position_target_budget(
        30_000.0,
        experiment,
        code="AAA",
        signal_meta={"score": 60.0},
    )
    strong = bt._position_target_budget(
        30_000.0,
        experiment,
        code="AAA",
        signal_meta={"score": 70.0},
    )
    low_vol = bt._position_target_budget(
        30_000.0,
        experiment,
        code="BBB",
        signal_meta={"score": 52.0},
    )

    assert weak == 18_000.0
    assert medium == 24_000.0
    assert strong == 30_000.0
    assert low_vol == 30_000.0


def test_high_vol_quality_composite_can_override_high_vol_stop_threshold():
    threshold = PortfolioBacktest._stop_loss_threshold(
        experiment=AblationExperimentConfig(
            name="quality",
            label="质量组合",
            use_config_stop_loss_profiles=True,
        ),
        risk_info={"atr_pct": 0.04},
        stop_loss_profile="atr_2_5",
        high_vol_quality_rule=HIGH_VOL_QUALITY_COMPOSITE,
    )

    assert threshold == -0.12


def test_format_high_vol_quality_control_report_shows_quality_stats():
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
        "stats": {
            "quality_entry_blocked": 12,
            "quality_daily_limit_blocked": 3,
            "quality_add_blocked": 4,
            "quality_budget_scaled": 5,
        },
        "experiment": {"label": "质量组合"},
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
                            "high_vol_quality_composite": candidate,
                        },
                    }
                ],
            }
        ],
    }

    report = format_high_vol_quality_control_report(result)

    assert "高波新信号交易质量控制实验报告" in report
    assert "组合候选" in report
    assert "质量组合" in report
    assert "+30" in report
    assert "质入拦" in report
