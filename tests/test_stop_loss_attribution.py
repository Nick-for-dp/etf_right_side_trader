"""止损归因辅助函数测试。"""

from datetime import date

from src.backtest.stop_loss_attribution_report import (
    _atr_bucket,
    _forward_return,
    _parse_threshold,
)


def test_parse_threshold_reads_percent_tail():
    assert _parse_threshold("stop_loss:-8.00%") == -0.08
    assert _parse_threshold("atr_2_5 浮亏 -10.00% ≤ 止损线 -10.00%，强制卖出") is None
    assert _parse_threshold(None) is None


def test_atr_bucket_boundaries():
    assert _atr_bucket(None) == "unknown"
    assert _atr_bucket(0.015) == "<2%"
    assert _atr_bucket(0.03) == "2-4%"
    assert _atr_bucket(0.05) == "4-6%"
    assert _atr_bucket(0.08) == "≥6%"


def test_forward_return_uses_trading_days_after_exit():
    price_map = {"AAA": {
        "2026-01-05": 10.0,
        "2026-01-06": 10.5,
        "2026-01-07": 11.0,
    }}
    assert round(_forward_return(price_map, "AAA", date(2026, 1, 5), 2), 4) == 0.1
    assert _forward_return(price_map, "AAA", date(2026, 1, 5), 5) is None
