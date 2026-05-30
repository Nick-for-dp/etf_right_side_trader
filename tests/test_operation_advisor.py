"""操作建议生成器单元测试。"""

from datetime import date

import pandas as pd

from src.advisor.operation_advisor import generate_advice
from src.models import AdviceAction, SignalSource, SignalType


def _signals(signal: str, signal_date: str = "2026-05-10") -> pd.DataFrame:
    return pd.DataFrame([{
        "code": "588000",
        "date": signal_date,
        "signal": signal,
        "signal_meta": {},
    }])


def _position() -> dict:
    return {
        "id": 1,
        "code": "588000",
        "cost": 1.0,
        "shares": 1000,
        "entry_date": "2026-05-01",
    }


def test_recent_buy_blocks_add_advice():
    """近 5 天已有建仓/加仓时，BUY 不再提示加仓。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        last_buy_dates={"588000": date(2026, 5, 7)},
        add_cooldown_days=5,
    )

    assert advices[0]["advice"] == AdviceAction.HOLD.value
    assert advices[0]["signal_source"] == SignalSource.ADD_COOLDOWN.value


def test_add_advice_allowed_after_cooldown():
    """超过冷却期后，BUY 可正常提示加仓。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        last_buy_dates={"588000": date(2026, 5, 5)},
        add_cooldown_days=5,
    )

    assert advices[0]["advice"] == AdviceAction.ADD.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_add_cooldown_does_not_block_sell():
    """加仓冷却不影响卖出建议。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.SELL.value),
        current_prices={"588000": 0.95},
        last_buy_dates={"588000": date(2026, 5, 9)},
        add_cooldown_days=5,
    )

    assert advices[0]["advice"] == AdviceAction.SELL.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_add_cooldown_does_not_block_new_position():
    """冷却机制只限制加仓，不限制空仓建仓。"""
    advices = generate_advice(
        positions=[],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        last_buy_dates={"588000": date(2026, 5, 9)},
        add_cooldown_days=5,
    )

    assert advices[0]["advice"] == AdviceAction.OPEN.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_hot_market_blocks_open_advice():
    """市场过热时，空仓 BUY 降级为观望。"""
    advices = generate_advice(
        positions=[],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "HOT"},
    )

    assert advices[0]["advice"] == AdviceAction.WATCH.value
    assert advices[0]["signal_source"] == SignalSource.MARKET_REGIME.value


def test_cold_market_blocks_add_advice():
    """市场过冷时，持仓 BUY 降级为继续持有。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "COLD"},
    )

    assert advices[0]["advice"] == AdviceAction.HOLD.value
    assert advices[0]["signal_source"] == SignalSource.MARKET_REGIME.value


def test_unknown_market_does_not_block_open_advice():
    """市场状态未知时回退原策略，不做拦截。"""
    advices = generate_advice(
        positions=[],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "UNKNOWN"},
    )

    assert advices[0]["advice"] == AdviceAction.OPEN.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_market_regime_does_not_block_sell():
    """市场热度门控不影响 SELL。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.SELL.value),
        current_prices={"588000": 0.95},
        market_regime={"state": "HOT"},
    )

    assert advices[0]["advice"] == AdviceAction.SELL.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_risk_signal_has_priority_over_market_regime():
    """风控 SELL 优先级高于市场热度门控。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 0.9},
        risk_signals={"588000": {"signal": SignalType.SELL.value, "source": SignalSource.STOP_LOSS.value}},
        market_regime={"state": "HOT"},
    )

    assert advices[0]["advice"] == AdviceAction.SELL.value
    assert advices[0]["signal_source"] == SignalSource.STOP_LOSS.value
