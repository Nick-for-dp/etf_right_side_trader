"""ETF tier classification report tests."""

from src.backtest.etf_tier_classification_report import (
    classify_etf,
    format_etf_tier_classification_report,
)
from src.config.settings_reader import EtfItem


def test_classify_etf_uses_manual_tier_profiles():
    power = classify_etf(EtfItem(
        symbol="159611",
        name="电力ETF广发",
        sector="电力",
        theme="电力指数",
    ))
    broker = classify_etf(EtfItem(
        symbol="512880",
        name="证券ETF国泰",
        sector="非银金融",
        theme="证券公司",
    ))

    assert power.strategy_tier == "C"
    assert power.prior_tier == "C"
    assert power.theme_primary == "防御公用"
    assert broker.strategy_tier == "A"
    assert broker.prior_tier == "A"
    assert broker.theme_primary == "金融弹性"


def test_format_etf_tier_classification_report_shows_universe_sections():
    result = {
        "meta": {
            "codes": ["512880", "159611"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
        },
        "profiles": [
            classify_etf(EtfItem(symbol="512880", name="证券ETF国泰", sector="非银金融", theme="证券公司")),
            classify_etf(EtfItem(symbol="159611", name="电力ETF广发", sector="电力", theme="电力指数")),
        ],
        "single_evaluations": [
            {
                "symbol": "512880",
                "name": "证券ETF国泰",
                "prior_tier": "A",
                "tier": "A",
                "reason": "长周期达标",
                "summary": _summary("12.00%", "18.00%", "0.6667"),
            },
            {
                "symbol": "159611",
                "name": "电力ETF广发",
                "prior_tier": "C",
                "tier": "C",
                "reason": "长周期不达标",
                "summary": _summary("3.00%", "12.00%", "0.2500"),
            },
        ],
        "windows": [
            {
                "label": "2016-2026",
                "start": "2016-01-01",
                "end": "2026-06-03",
                "rows": [
                    {"name": "full", "label": "全池", "codes": ["512880", "159611"], "summary": _summary("10.00%", "20.00%", "0.5000")},
                    {"name": "tier_ab", "label": "A+B排除C", "codes": ["512880"], "summary": _summary("12.00%", "18.00%", "0.6667")},
                    {"name": "tier_c", "label": "C类观察", "codes": ["159611"], "summary": _summary("3.00%", "12.00%", "0.2500")},
                ],
                "decision": "demo",
            }
        ],
    }

    report = format_etf_tier_classification_report(result)

    assert "ETF A/B/C 分类" in report
    assert "单 ETF 长周期资格评估" in report
    assert "A+B排除C" in report
    assert "C类观察" in report
    assert "电力ETF广发" in report


def _summary(annual: str, drawdown: str, calmar: str) -> dict:
    return {
        "annual_return": annual,
        "max_drawdown": drawdown,
        "calmar": calmar,
        "sharpe": "1.0000",
        "win_rate": "50.00%",
        "profit_factor": "1.5000",
        "total_trades": "10",
    }
