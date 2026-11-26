"""Portfolio risk-control experiment tests."""

from src.backtest.ablation_config import (
    portfolio_risk_control_combo_experiments,
    portfolio_risk_control_experiments,
    portfolio_risk_control_single_experiments,
)
from src.backtest.portfolio_risk_control_report import (
    ANCHOR_NAME,
    BASELINE_NAME,
    format_portfolio_risk_control_report,
)


def test_portfolio_risk_control_matrix_contains_anchor_and_candidates():
    experiments = portfolio_risk_control_experiments()

    assert [exp.name for exp in experiments[:2]] == [BASELINE_NAME, ANCHOR_NAME]
    assert experiments[1].high_vol_quality_rule.name == ANCHOR_NAME
    assert experiments[1].experimental_signal_profile.name == "signal_high_vol_balanced"
    assert {exp.portfolio_risk_rule.name for exp in experiments[2:]} == {
        "portfolio_single_25",
        "portfolio_total_85",
        "portfolio_high_vol_25",
        "portfolio_high_vol_20",
        "portfolio_max_positions_10",
        "portfolio_high_vol_count_4",
        "portfolio_risk_moderate",
        "portfolio_risk_conservative",
    }


def test_portfolio_risk_control_subsets_are_focused():
    single = portfolio_risk_control_single_experiments()
    combo = portfolio_risk_control_combo_experiments()

    assert [exp.name for exp in single[:2]] == [BASELINE_NAME, ANCHOR_NAME]
    assert {exp.portfolio_risk_rule.name for exp in single[2:]} == {
        "portfolio_single_25",
        "portfolio_total_85",
        "portfolio_high_vol_25",
        "portfolio_high_vol_20",
        "portfolio_max_positions_10",
        "portfolio_high_vol_count_4",
    }
    assert [exp.name for exp in combo] == [
        BASELINE_NAME,
        ANCHOR_NAME,
        "portfolio_risk_moderate",
        "portfolio_risk_conservative",
    ]


def test_format_portfolio_risk_control_report_shows_stats_and_decision():
    rows = [
        _row(BASELINE_NAME, "baseline-v2.4", "11.00%", "26.00%", "0.4231", 0.30, 0.69, 0.28, 0, 0, False),
        _row(ANCHOR_NAME, "全池质量分层", "15.00%", "22.00%", "0.6818", 0.34, 0.66, 0.18, 0, 0, False),
        _row("portfolio_risk_moderate", "组合温和控险", "15.30%", "19.00%", "0.8053", 0.38, 0.62, 0.15, 3, 8, True),
    ]
    result = {
        "meta": {
            "codes": ["AAA", "BBB"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
        },
        "windows": [{
            "label": "2016-2026",
            "start": "2016-01-01",
            "end": "2026-06-03",
            "rows": rows,
            "decision": "组合温和控险 是当前最优组合风控候选，判断为优先。",
        }],
    }

    report = format_portfolio_risk_control_report(result)

    assert "组合风险控制实验报告" in report
    assert "收益、回撤与平均暴露" in report
    assert "相对全池质量分层的暴露变化" in report
    assert "风险触发统计" in report
    assert "组合温和控险" in report
    assert "优先" in report


def _row(name, label, annual, drawdown, calmar, cash, market, high_vol, blocked, scaled, has_risk):
    return {
        "name": name,
        "label": label,
        "summary": {
            "annual_return": annual,
            "max_drawdown": drawdown,
            "calmar": calmar,
            "profit_factor": "2.0000",
            "total_trades": "10",
        },
        "stats": {
            "portfolio_risk_blocked": blocked,
            "portfolio_risk_scaled": scaled,
            "portfolio_risk_position_count_blocked": 1 if blocked else 0,
            "portfolio_risk_high_vol_count_blocked": 0,
            "portfolio_risk_single_position_blocked": 0,
            "portfolio_risk_single_position_scaled": scaled,
            "portfolio_risk_total_exposure_blocked": 0,
            "portfolio_risk_total_exposure_scaled": 0,
            "portfolio_risk_high_vol_exposure_blocked": 0,
            "portfolio_risk_high_vol_exposure_scaled": 0,
        },
        "attribution": {
            "avg_cash_ratio": cash,
            "avg_market_ratio": market,
            "avg_exposure": {
                "vol:high_vol": high_vol,
                "vol:low_vol": market - high_vol,
            },
        },
        "has_portfolio_risk": has_risk,
    }
