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
        "signal_meta": {"score": 65},
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


def test_add_budget_blocks_add_when_not_profitable():
    """70/15/15 加仓规则要求浮盈后才允许加仓。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 0.99},
        entry_add_budget={
            "entry_ratio": 0.7,
            "add_steps": [{"ratio": 0.15, "require_profit": True, "min_score": 60}],
        },
    )

    assert advices[0]["advice"] == AdviceAction.HOLD.value
    assert advices[0]["signal_source"] == SignalSource.ADD_BUDGET.value


def test_add_budget_blocks_add_when_score_too_low():
    """70/15/15 加仓规则要求下一阶梯 score 达标。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        entry_add_budget={
            "entry_ratio": 0.7,
            "add_steps": [{"ratio": 0.15, "require_profit": True, "min_score": 70}],
        },
    )

    assert advices[0]["advice"] == AdviceAction.HOLD.value
    assert advices[0]["signal_source"] == SignalSource.ADD_BUDGET.value


def test_add_budget_blocks_add_after_all_steps_used():
    """70/15/15 最多执行配置中的两次加仓。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        add_counts={"588000": 2},
        entry_add_budget={
            "entry_ratio": 0.7,
            "add_steps": [
                {"ratio": 0.15, "require_profit": True, "min_score": 60},
                {"ratio": 0.15, "require_profit": True, "min_score": 70},
            ],
        },
    )

    assert advices[0]["advice"] == AdviceAction.HOLD.value
    assert advices[0]["signal_source"] == SignalSource.ADD_BUDGET.value


def test_open_advice_contains_entry_budget_explanation():
    """空仓 BUY 建议落库 70% 建仓预算和解释字段。"""
    advices = generate_advice(
        positions=[],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "NORMAL", "score": 0.2},
        entry_add_budget={
            "entry_ratio": 0.7,
            "add_steps": [{"ratio": 0.15, "require_profit": True, "min_score": 60}],
        },
        stop_loss_profiles={"588000": "atr_2_5"},
    )

    advice = advices[0]
    assert advice["advice"] == AdviceAction.OPEN.value
    assert advice["target_budget_ratio"] == 0.7
    assert advice["target_position_ratio"] == 0.7
    assert advice["entry_add_step"] is None
    assert advice["score"] == 65
    assert advice["market_state"] == "NORMAL"
    assert advice["stop_loss_profile"] == "atr_2_5"
    assert advice["advice_meta"]["budget_plan"]["stage"] == "entry"


def test_add_advice_contains_next_step_budget_explanation():
    """持仓 BUY 建议落库下一次 15% 加仓阶梯。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        add_counts={"588000": 1},
        entry_add_budget={
            "entry_ratio": 0.7,
            "add_steps": [
                {"ratio": 0.15, "require_profit": True, "min_score": 60},
                {"ratio": 0.15, "require_profit": True, "min_score": 60},
            ],
        },
    )

    advice = advices[0]
    assert advice["advice"] == AdviceAction.ADD.value
    assert advice["target_budget_ratio"] == 0.15
    assert advice["target_position_ratio"] == 1.0
    assert advice["entry_add_step"] == 2
    assert advice["blocked_reason"] is None
    assert advice["advice_meta"]["budget_plan"]["stage"] == "add"


def test_add_budget_block_records_reason_and_budget_plan():
    """加仓预算不满足时，保留下一阶梯预算和拦截原因。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 0.99},
        entry_add_budget={
            "entry_ratio": 0.7,
            "add_steps": [{"ratio": 0.15, "require_profit": True, "min_score": 60}],
        },
    )

    advice = advices[0]
    assert advice["advice"] == AdviceAction.HOLD.value
    assert advice["signal_source"] == SignalSource.ADD_BUDGET.value
    assert advice["target_budget_ratio"] == 0.15
    assert advice["entry_add_step"] == 1
    assert advice["blocked_reason"] == "add_budget:not_profitable"
    assert advice["advice_meta"]["blocked_reason"] == "add_budget:not_profitable"


def test_risk_signal_records_reason_and_profile():
    """风控覆盖时，建议解释包含风控原因和止损 profile。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 0.9},
        risk_signals={
            "588000": {
                "signal": SignalType.SELL.value,
                "source": SignalSource.STOP_LOSS.value,
                "reason": "atr_2_5 浮亏触发",
                "stop_loss_profile": "atr_2_5",
            }
        },
    )

    advice = advices[0]
    assert advice["advice"] == AdviceAction.SELL.value
    assert advice["blocked_reason"] == "atr_2_5 浮亏触发"
    assert advice["stop_loss_profile"] == "atr_2_5"
    assert advice["advice_meta"]["risk_reason"] == "atr_2_5 浮亏触发"


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


def test_hot_falling_market_blocks_open_advice():
    """RISK_OFF 时，空仓 BUY 降级为观望。"""
    advices = generate_advice(
        positions=[],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "RISK_OFF"},
    )

    assert advices[0]["advice"] == AdviceAction.WATCH.value
    assert advices[0]["signal_source"] == SignalSource.MARKET_REGIME.value


def test_hot_rising_market_does_not_block_open_advice():
    """NORMAL 时允许空仓 BUY。"""
    advices = generate_advice(
        positions=[],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "NORMAL"},
    )

    assert advices[0]["advice"] == AdviceAction.OPEN.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_bear_trend_market_blocks_add_advice():
    """RISK_OFF 时，持仓 BUY 降级为继续持有。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "RISK_OFF"},
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


def test_recovery_market_allows_open_advice():
    """NORMAL 时，空仓 BUY 允许建仓。"""
    advices = generate_advice(
        positions=[],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 1.05},
        market_regime={"state": "NORMAL"},
    )

    assert advices[0]["advice"] == AdviceAction.OPEN.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_market_regime_does_not_block_sell():
    """市场状态门控不影响 SELL。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.SELL.value),
        current_prices={"588000": 0.95},
        market_regime={"state": "RISK_OFF"},
    )

    assert advices[0]["advice"] == AdviceAction.SELL.value
    assert advices[0]["signal_source"] == SignalSource.TREND.value


def test_risk_signal_has_priority_over_market_regime():
    """风控 SELL 优先级高于市场状态门控。"""
    advices = generate_advice(
        positions=[_position()],
        signals=_signals(SignalType.BUY.value),
        current_prices={"588000": 0.9},
        risk_signals={"588000": {"signal": SignalType.SELL.value, "source": SignalSource.STOP_LOSS.value}},
        market_regime={"state": "RISK_OFF"},
    )

    assert advices[0]["advice"] == AdviceAction.SELL.value
    assert advices[0]["signal_source"] == SignalSource.STOP_LOSS.value


def test_high_vol_quality_tier_scales_open_budget_by_score():
    budget_override = {
        "high_vol": {
            "enabled": True,
            "kind": "quality_tier",
            "strong_score": 65,
            "strong_multiplier": 1.0,
            "medium_score": 55,
            "medium_multiplier": 0.8,
            "weak_multiplier": 0.6,
        }
    }

    weak = generate_advice(
        positions=[],
        signals=pd.DataFrame([{
            "code": "AAA",
            "date": "2026-05-10",
            "signal": SignalType.BUY.value,
            "signal_meta": {"score": 52},
        }]),
        current_prices={"AAA": 1.0},
        entry_add_budget={"entry_ratio": 0.7, "add_steps": []},
        entry_budget_overrides=budget_override,
        code_volatility_groups={"AAA": "high_vol"},
    )[0]
    medium = generate_advice(
        positions=[],
        signals=pd.DataFrame([{
            "code": "AAA",
            "date": "2026-05-10",
            "signal": SignalType.BUY.value,
            "signal_meta": {"score": 60},
        }]),
        current_prices={"AAA": 1.0},
        entry_add_budget={"entry_ratio": 0.7, "add_steps": []},
        entry_budget_overrides=budget_override,
        code_volatility_groups={"AAA": "high_vol"},
    )[0]
    strong = generate_advice(
        positions=[],
        signals=pd.DataFrame([{
            "code": "AAA",
            "date": "2026-05-10",
            "signal": SignalType.BUY.value,
            "signal_meta": {"score": 70},
        }]),
        current_prices={"AAA": 1.0},
        entry_add_budget={"entry_ratio": 0.7, "add_steps": []},
        entry_budget_overrides=budget_override,
        code_volatility_groups={"AAA": "high_vol"},
    )[0]

    assert weak["target_budget_ratio"] == 0.42
    assert weak["advice_meta"]["budget_plan"]["budget_quality_tier"] == "weak"
    assert medium["target_budget_ratio"] == 0.5599999999999999
    assert medium["advice_meta"]["budget_plan"]["budget_quality_tier"] == "medium"
    assert strong["target_budget_ratio"] == 0.7
    assert strong["advice_meta"]["budget_plan"]["budget_quality_tier"] == "strong"


def test_high_vol_quality_tier_scales_add_budget_by_score():
    budget_override = {
        "high_vol": {
            "enabled": True,
            "kind": "quality_tier",
            "strong_score": 65,
            "strong_multiplier": 1.0,
            "medium_score": 55,
            "medium_multiplier": 0.8,
            "weak_multiplier": 0.6,
        }
    }

    advices = generate_advice(
        positions=[{
            "id": 2,
            "code": "AAA",
            "cost": 1.0,
            "shares": 1000,
            "entry_date": "2026-05-01",
        }],
        signals=pd.DataFrame([{
            "code": "AAA",
            "date": "2026-05-10",
            "signal": SignalType.BUY.value,
            "signal_meta": {"score": 60},
        }]),
        current_prices={"AAA": 1.1},
        entry_add_budget={
            "entry_ratio": 0.7,
            "add_steps": [{"ratio": 0.15, "require_profit": True, "min_score": 60}],
        },
        entry_budget_overrides=budget_override,
        code_volatility_groups={"AAA": "high_vol"},
    )

    advice = advices[0]
    assert advice["advice"] == AdviceAction.ADD.value
    assert advice["target_budget_ratio"] == 0.12
    assert advice["target_position_ratio"] == 0.68
    assert advice["advice_meta"]["budget_plan"]["budget_quality_tier"] == "medium"


def test_quality_tier_does_not_affect_low_vol_budget():
    advices = generate_advice(
        positions=[],
        signals=pd.DataFrame([{
            "code": "BBB",
            "date": "2026-05-10",
            "signal": SignalType.BUY.value,
            "signal_meta": {"score": 52},
        }]),
        current_prices={"BBB": 1.0},
        entry_add_budget={"entry_ratio": 0.7, "add_steps": []},
        entry_budget_overrides={
            "high_vol": {
                "enabled": True,
                "kind": "quality_tier",
                "strong_score": 65,
                "strong_multiplier": 1.0,
                "medium_score": 55,
                "medium_multiplier": 0.8,
                "weak_multiplier": 0.6,
            }
        },
        code_volatility_groups={"BBB": "low_vol"},
    )

    assert advices[0]["target_budget_ratio"] == 0.7
    assert advices[0]["advice_meta"]["entry_budget_override"] == {}
