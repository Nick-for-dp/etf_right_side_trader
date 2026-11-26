"""Volatility focus anchor report tests."""

from src.backtest.volatility_focus_anchor_report import (
    BASELINE_NAME,
    HIGH_ONLY_NAME,
    LOW_ONLY_NAME,
    SATELLITE_NAME,
    TIER_NAME,
    format_volatility_focus_anchor_report,
    _order_rows,
    _window_decision,
)


def test_format_volatility_focus_anchor_report_shows_anchor_decision():
    rows = _sample_rows()
    result = {
        "meta": {
            "codes": ["AAA", "BBB", "CCC"],
            "low_vol_codes": ["BBB"],
            "high_vol_codes": ["AAA", "CCC"],
            "capital": 100_000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "max_satellite_high_vol_positions": 3,
        },
        "windows": [{
            "label": "2016-2026",
            "start": "2016-01-01",
            "end": "2026-06-03",
            "rows": _order_rows(rows),
            "decision": _window_decision(rows),
        }],
    }

    report = format_volatility_focus_anchor_report(result)

    assert "低波/高波策略重心锚点实验报告" in report
    assert "策略重心对比" in report
    assert "相对全池质量分层" in report
    assert "低波单独可作为主线锚点" in report
    assert "低波单独" in report
    assert "高波单独" in report
    assert "低波核心+高波卫星" in report


def test_order_rows_keeps_anchor_order():
    ordered = _order_rows([
        _row(TIER_NAME, "全池质量分层", "全池", "15.00%", "20.00%", "0.7500", 0.20, 0.45),
        _row(HIGH_ONLY_NAME, "高波单独", "高波", "8.00%", "24.00%", "0.3333", 0.40, 0.0),
        _row(BASELINE_NAME, "baseline-v2.4", "全池", "11.00%", "26.00%", "0.4231", 0.28, 0.41),
        _row(LOW_ONLY_NAME, "低波单独", "低波", "14.00%", "14.00%", "1.0000", 0.0, 0.60),
        _row(SATELLITE_NAME, "低波核心+高波卫星", "全池", "14.50%", "18.00%", "0.8056", 0.12, 0.50),
    ])

    assert [row["name"] for row in ordered] == [
        BASELINE_NAME,
        LOW_ONLY_NAME,
        HIGH_ONLY_NAME,
        SATELLITE_NAME,
        TIER_NAME,
    ]


def _sample_rows():
    return [
        _row(BASELINE_NAME, "baseline-v2.4", "全池", "11.00%", "26.00%", "0.4231", 0.28, 0.41),
        _row(LOW_ONLY_NAME, "低波单独", "低波", "14.00%", "14.00%", "1.0000", 0.0, 0.60),
        _row(HIGH_ONLY_NAME, "高波单独", "高波", "8.00%", "24.00%", "0.3333", 0.40, 0.0),
        _row(SATELLITE_NAME, "低波核心+高波卫星", "全池", "14.50%", "18.00%", "0.8056", 0.12, 0.50),
        _row(TIER_NAME, "全池质量分层", "全池", "15.00%", "20.00%", "0.7500", 0.20, 0.45),
    ]


def _row(name, label, scope, annual, drawdown, calmar, high_exposure, low_exposure):
    return {
        "name": name,
        "label": label,
        "scope": scope,
        "codes_count": 3,
        "summary": {
            "annual_return": annual,
            "max_drawdown": drawdown,
            "calmar": calmar,
            "sharpe": "1.0000",
            "win_rate": "50.00%",
            "profit_factor": "2.0000",
            "total_trades": "10",
        },
        "stats": {},
        "attribution": {
            "avg_cash_ratio": 0.2,
            "avg_exposure": {
                "vol:high_vol": high_exposure,
                "vol:low_vol": low_exposure,
            },
        },
    }
