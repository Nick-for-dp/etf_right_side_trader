"""High-vol quality capital attribution tests."""

from datetime import date

from src.backtest.high_vol_quality_capital_attribution_report import (
    format_high_vol_quality_capital_attribution_report,
    _attribute_version,
)
from src.backtest.portfolio_backtest import EquityPoint, TradeLog


def test_attribute_version_rebuilds_exposure_flows_and_pnl():
    version = {
        "experiment": {"label": "demo"},
        "equity_curve": [
            EquityPoint(date(2026, 1, 1), 100_000.0, 0.0, 100_000.0, "v"),
            EquityPoint(date(2026, 1, 2), 90_000.0, 10_000.0, 100_000.0, "v"),
            EquityPoint(date(2026, 1, 3), 80_000.0, 21_000.0, 101_000.0, "v"),
            EquityPoint(date(2026, 1, 4), 91_000.0, 10_000.0, 101_000.0, "v"),
        ],
        "trades": [
            TradeLog("AAA", date(2026, 1, 2), "建仓", 10.0, 1000, 0.0, 100_000.0, 90_000.0, "v"),
            TradeLog("BBB", date(2026, 1, 3), "建仓", 20.0, 500, 0.0, 90_000.0, 80_000.0, "v"),
            TradeLog("AAA", date(2026, 1, 4), "SELL", 11.0, 1000, 0.0, 80_000.0, 91_000.0, "v"),
        ],
    }
    price_map = {
        "AAA": {"2026-01-02": 10.0, "2026-01-03": 11.0, "2026-01-04": 11.0},
        "BBB": {"2026-01-03": 20.0, "2026-01-04": 20.0},
    }
    code_meta = {
        "AAA": {"volatility_group": "high_vol", "regime_group": "A股", "category": "sector"},
        "BBB": {"volatility_group": "low_vol", "regime_group": "美股", "category": "broad"},
    }

    attr = _attribute_version(version, price_map=price_map, code_meta=code_meta)

    assert attr["label"] == "demo"
    assert round(attr["avg_exposure"]["vol:high_vol"], 4) == round((0.10 + 11_000 / 101_000 + 0) / 4, 4)
    assert round(attr["avg_exposure"]["vol:low_vol"], 4) == round((10_000 / 101_000 + 10_000 / 101_000) / 4, 4)
    assert attr["flows"]["vol:high_vol"]["buy"] == 10_000.0
    assert attr["flows"]["vol:high_vol"]["sell"] == 11_000.0
    assert attr["flows"]["vol:high_vol"]["net_buy"] == -1_000.0
    assert attr["pnl"]["vol:high_vol"] == 1_000.0
    assert attr["pnl"]["vol:low_vol"] == 0.0
    assert round(attr["avg_code_exposure"]["AAA"], 4) == round((0.10 + 11_000 / 101_000 + 0) / 4, 4)
    assert attr["flows_by_code"]["AAA"]["net_buy"] == -1_000.0
    assert attr["pnl_by_code"]["AAA"] == 1_000.0
    assert attr["pnl_by_code"]["BBB"] == 0.0


def test_format_capital_attribution_report_shows_delta_sections():
    result = {
        "meta": {
            "codes": ["AAA", "BBB"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
        },
        "windows": [
            {
                "result": {
                    "meta": {"window": "2016-2026", "start": "2016-01-01", "end": "2026-06-03"},
                    "versions": {
                        "baseline_v2_4_segment_stop": _version("baseline-v2.4"),
                        "mixed_high_vol_signal": _version("高波新信号混合"),
                        "high_vol_quality_budget_tier": _version("质量分层仓位"),
                    },
                },
                "attribution": {
                    "baseline_v2_4_segment_stop": _attr("baseline-v2.4", 0.20, 0.30, 0.20, 1000, 2000),
                    "mixed_high_vol_signal": _attr("高波新信号混合", 0.10, 0.40, 0.20, 3000, 2000),
                    "high_vol_quality_budget_tier": _attr("质量分层仓位", 0.15, 0.35, 0.25, 2500, 2600),
                },
            }
        ],
    }

    report = format_high_vol_quality_capital_attribution_report(result)

    assert "组合资金再分配归因报告" in report
    assert "资金暴露" in report
    assert "交易现金流和收益贡献" in report
    assert "质量分层相对高波混合" in report
    assert "高波暴露" in report
    assert "单 ETF 暴露变化" in report
    assert "单 ETF 收益变化" in report
    assert "AAA" in report


def _version(label):
    return {
        "summary": {
            "annual_return": "10.00%",
            "max_drawdown": "20.00%",
            "calmar": "0.5000",
            "profit_factor": "1.5000",
            "total_trades": "10",
        },
        "experiment": {"label": label},
    }


def _attr(label, cash, high_exposure, low_exposure, high_pnl, low_pnl):
    return {
        "label": label,
        "avg_cash_ratio": cash,
        "avg_exposure": {
            "vol:high_vol": high_exposure,
            "vol:low_vol": low_exposure,
            "market:A股": high_exposure,
            "market:港股": 0.0,
            "market:美股": low_exposure,
        },
        "flows": {
            "vol:high_vol": {"buy": 10_000.0, "sell": 8_000.0, "net_buy": 2_000.0},
            "vol:low_vol": {"buy": 5_000.0, "sell": 1_000.0, "net_buy": 4_000.0},
        },
        "pnl": {"vol:high_vol": high_pnl, "vol:low_vol": low_pnl},
        "code_meta": {
            "AAA": {"name": "AAA", "volatility_group": "high_vol", "regime_group": "A股"},
            "BBB": {"name": "BBB", "volatility_group": "low_vol", "regime_group": "美股"},
        },
        "avg_code_exposure": {
            "AAA": high_exposure,
            "BBB": low_exposure,
        },
        "flows_by_code": {
            "AAA": {"buy": 10_000.0, "sell": 8_000.0, "net_buy": 2_000.0},
            "BBB": {"buy": 5_000.0, "sell": 1_000.0, "net_buy": 4_000.0},
        },
        "pnl_by_code": {"AAA": high_pnl, "BBB": low_pnl},
    }
