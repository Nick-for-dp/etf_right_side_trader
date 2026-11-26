"""High-vol quality-tier robustness tests."""

from src.backtest.ablation_config import (
    high_vol_quality_tier_candidate_experiments,
    high_vol_quality_tier_sensitivity_experiments,
)
from src.backtest.high_vol_quality_tier_robustness_report import (
    format_high_vol_quality_tier_robustness_report,
)


def test_quality_tier_sensitivity_matrix_contains_candidate_variants():
    experiments = high_vol_quality_tier_sensitivity_experiments()

    assert [exp.name for exp in experiments[:2]] == [
        "baseline_v2_4_segment_stop",
        "mixed_high_vol_signal",
    ]
    assert {exp.high_vol_quality_rule.name for exp in experiments[2:]} == {
        "high_vol_quality_budget_tier",
        "high_vol_quality_tier_mild",
        "high_vol_quality_tier_strict",
        "high_vol_quality_tier_defensive",
    }


def test_quality_tier_candidate_matrix_is_focused():
    experiments = high_vol_quality_tier_candidate_experiments()

    assert [exp.name for exp in experiments] == [
        "baseline_v2_4_segment_stop",
        "mixed_high_vol_signal",
        "high_vol_quality_budget_tier",
    ]
    assert experiments[2].high_vol_quality_rule.name == "high_vol_quality_budget_tier"
    assert experiments[2].experimental_signal_profile.name == "signal_high_vol_balanced"


def test_format_quality_tier_robustness_report_shows_sections():
    baseline = _version("baseline-v2.4", "10.00%", "20.00%", "0.5000", "1.5000", "100")
    mixed = _version("高波新信号混合", "15.00%", "22.00%", "0.6818", "1.8000", "150")
    tier = _version("质量分层仓位", "16.00%", "18.00%", "0.8889", "2.1000", "151", {"quality_budget_scaled": 30})
    window = {
        "meta": {"window": "2016-2026", "start": "2016-01-01", "end": "2026-06-03"},
        "versions": {
            "baseline_v2_4_segment_stop": baseline,
            "mixed_high_vol_signal": mixed,
            "high_vol_quality_budget_tier": tier,
        },
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
        "sensitivity_windows": [window],
        "rolling_windows": [window],
        "segments": [{"name": "全部高波", "codes": ["AAA"], "result": window}],
        "etfs": [{"symbol": "AAA", "market": "A股", "result": window, "judgement": "稳健"}],
    }

    report = format_high_vol_quality_tier_robustness_report(result)

    assert "高波质量分层仓位稳健性验证报告" in report
    assert "一、参数敏感性" in report
    assert "二、滚动窗口" in report
    assert "三、分市场归因" in report
    assert "四、单 ETF 归因" in report
    assert "质量分层仓位" in report


def _version(label, annual, drawdown, calmar, pf, trades, stats=None):
    return {
        "summary": {
            "annual_return": annual,
            "max_drawdown": drawdown,
            "calmar": calmar,
            "sharpe": "0.8000",
            "win_rate": "40.00%",
            "profit_factor": pf,
            "total_trades": trades,
        },
        "stats": stats or {},
        "experiment": {"label": label},
    }
