"""Stop-loss attribution report tests."""

from datetime import date

from src.backtest.portfolio_backtest import TradeLog
from src.backtest.stop_loss_attribution_report import (
    build_stop_loss_events,
    format_stop_loss_attribution_report,
    _summarize_by,
    _summary,
)


def test_build_stop_loss_events_adds_forward_returns_and_secondary_stop():
    version = {
        "summary": {"annual_return": "10.00%", "max_drawdown": "12.00%"},
        "trades": [
            TradeLog("AAA", date(2026, 1, 2), "建仓", 10.0, 1000, 0.0, 100_000, 90_000, "v"),
            TradeLog(
                "AAA",
                date(2026, 1, 4),
                "SELL",
                9.0,
                1000,
                0.0,
                90_000,
                99_000,
                "v",
                signal_source="stop_loss",
                reason="stop_loss:-8.00%",
            ),
            TradeLog("AAA", date(2026, 1, 5), "建仓", 9.5, 1000, 0.0, 99_000, 89_500, "v"),
            TradeLog(
                "AAA",
                date(2026, 1, 7),
                "SELL",
                8.5,
                1000,
                0.0,
                89_500,
                98_000,
                "v",
                signal_source="stop_loss",
                reason="stop_loss:-10.00%",
            ),
        ],
    }
    trading_days = [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
        "2026-01-04",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
        "2026-01-08",
        "2026-01-09",
        "2026-01-10",
        "2026-01-11",
    ]
    price_map = {
        "AAA": {
            "2026-01-03": 9.1,
            "2026-01-04": 9.0,
            "2026-01-07": 8.5,
            "2026-01-09": 9.9,
        }
    }
    indicator_map = {
        "AAA": {
            "2026-01-03": {"atr_pct": 0.035, "adx14": 22, "rsi": 38},
            "2026-01-06": {"atr_pct": 0.065, "adx14": 18, "rsi": 35},
        }
    }
    regime_by_day = {
        "2026-01-03": {"AAA": {"state": "PANIC"}},
        "2026-01-06": {"AAA": {"state": "BEAR_TREND"}},
    }
    code_meta = {
        "AAA": {
            "name": "Demo ETF",
            "market": "A股",
            "regime_group": "A股",
            "volatility_group": "high_vol",
            "stop_loss_profile": "atr_2_5",
        }
    }

    events = build_stop_loss_events(
        version,
        trading_days=trading_days,
        price_map=price_map,
        indicator_map=indicator_map,
        regime_by_day=regime_by_day,
        code_meta=code_meta,
    )

    assert len(events) == 2
    assert events[0]["market_state"] == "PANIC"
    assert events[0]["atr_bucket"] == "2-4%"
    assert events[0]["threshold_pct"] == -0.08
    assert round(events[0]["ret_5d"], 4) == 0.1
    assert events[0]["secondary_stop_loss"] is True
    assert events[1]["atr_bucket"] == ">=6%"


def test_format_stop_loss_attribution_report_shows_core_sections():
    version = {
        "summary": {"annual_return": "10.00%", "max_drawdown": "12.00%"},
        "trades": [
            TradeLog("AAA", date(2026, 1, 2), "建仓", 10.0, 1000, 0.0, 100_000, 90_000, "v"),
            TradeLog(
                "AAA",
                date(2026, 1, 4),
                "SELL",
                9.0,
                1000,
                0.0,
                90_000,
                99_000,
                "v",
                signal_source="stop_loss",
                reason="stop_loss:-8.00%",
            ),
        ],
    }
    events = [
        {
            "code": "AAA",
            "name": "Demo ETF",
            "exit_date": date(2026, 1, 4),
            "pnl_cash": -1000.0,
            "pnl_pct": -0.10,
            "holding_days": 2,
            "volatility_group": "high_vol",
            "stop_loss_profile": "atr_2_5",
            "market_state": "PANIC",
            "atr_bucket": "2-4%",
            "atr_pct": 0.035,
            "ret_5d": 0.02,
            "ret_10d": None,
            "ret_20d": None,
            "ret_60d": None,
            "has_next_trade": False,
            "secondary_stop_loss": False,
        }
    ]
    code_meta = {
        "AAA": {
            "name": "Demo ETF",
            "volatility_group": "high_vol",
            "regime_group": "A股",
            "stop_loss_profile": "atr_2_5",
        }
    }
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-31",
            "codes": ["AAA"],
            "capital": 100_000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "label": "v2.5 limited",
        },
        "summary": _summary(version, [], events),
        "by_etf": _summarize_by(events, "code", code_meta=code_meta),
        "by_market_state": _summarize_by(events, "market_state"),
        "by_volatility_group": _summarize_by(events, "volatility_group"),
        "by_stop_loss_profile": _summarize_by(events, "stop_loss_profile"),
        "by_atr_bucket": _summarize_by(events, "atr_bucket"),
        "events": events,
    }

    report = format_stop_loss_attribution_report(result)

    assert "止损事件级归因报告" in report
    assert "高波 ETF 止损损益来源" in report
    assert "按 ATR 桶拆解" in report
    assert "Demo ETF" in report
