"""High-vol mixed strategy validation tests."""

from src.backtest.ablation_config import high_vol_mixed_strategy_experiments
from src.backtest.high_vol_mixed_strategy_report import format_high_vol_mixed_strategy_report


def test_high_vol_mixed_strategy_experiments_keep_baseline_risk():
    experiments = high_vol_mixed_strategy_experiments()

    assert [exp.name for exp in experiments] == [
        "baseline_v2_4_segment_stop",
        "mixed_high_vol_signal",
    ]
    baseline, candidate = experiments
    assert baseline.experimental_signal_profile is None
    assert candidate.experimental_signal_profile.name == "signal_high_vol_balanced"
    assert candidate.experimental_signal_profile.volatility_groups == ("high_vol",)
    assert candidate.experimental_risk_profile is None
    assert candidate.use_config_stop_loss_profiles is True
    assert candidate.max_holding_days == 90
    assert candidate.entry_add_budget_rule.name == "budget_70_15_15_ladder"


def test_format_high_vol_mixed_strategy_report_shows_windows_and_deltas():
    window = {
        "meta": {
            "window": "2016-2026",
            "start": "2016-01-01",
            "end": "2026-06-03",
        },
        "versions": {
            "baseline_v2_4_segment_stop": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "calmar": "0.5000",
                    "sharpe": "0.6000",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "2",
                },
                "stats": {"stop_loss_triggered": 1, "max_holding_exit": 2, "add_executed": 3},
                "experiment": {"label": "baseline-v2.4"},
            },
            "mixed_high_vol_signal": {
                "summary": {
                    "annual_return": "12.00%",
                    "max_drawdown": "18.00%",
                    "calmar": "0.6667",
                    "sharpe": "0.7000",
                    "win_rate": "52.00%",
                    "profit_factor": "1.7000",
                    "total_trades": "3",
                },
                "stats": {"stop_loss_triggered": 1, "max_holding_exit": 1, "add_executed": 4},
                "experiment": {"label": "高波新信号混合"},
            },
        },
    }
    result = {
        "meta": {
            "codes": ["AAA", "BBB"],
            "high_vol_codes": ["AAA"],
            "low_vol_codes": ["BBB"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
        },
        "windows": [window],
    }

    report = format_high_vol_mixed_strategy_report(result)

    assert "高波新信号全池混合验证报告" in report
    assert "区间: 2016-2026" in report
    assert "高波新信号混合" in report
    assert "+2.00%" in report
    assert "high_vol: AAA" in report
