"""Risk controller tests."""

from datetime import date
from types import SimpleNamespace

from src.risk import MaxHoldingDaysRule, ProfileStopLossRule, RiskController


def test_profile_stop_loss_uses_atr_threshold_with_clamps():
    rule = ProfileStopLossRule()
    position = {
        "code": "AAA",
        "cost": 10.0,
        "atr_pct": 0.04,
        "stop_loss_profile": "atr_2_5",
    }

    assert rule.check(position, 9.01) is None
    result = rule.check(position, 9.0)

    assert result is not None
    assert result.source == "stop_loss"
    assert "atr_2_5" in result.reason


def test_profile_stop_loss_none_disables_stop_loss():
    rule = ProfileStopLossRule()
    position = {
        "code": "AAA",
        "cost": 10.0,
        "atr_pct": 0.04,
        "stop_loss_profile": "none",
    }

    assert rule.check(position, 1.0) is None


def test_max_holding_days_rule_triggers_at_limit():
    rule = MaxHoldingDaysRule(max_days=90)
    position = {
        "code": "AAA",
        "cost": 10.0,
        "entry_date": date(2026, 1, 1),
        "as_of_date": date(2026, 4, 1),
    }

    result = rule.check(position, 11.0)

    assert result is not None
    assert result.source == "max_holding"


def test_risk_controller_loads_baseline_v2_4_rules():
    config = SimpleNamespace(
        risk_rules=[
            {"type": "profile_stop_loss", "params": {"default_profile": "fixed_8"}},
            {"type": "max_holding_days", "params": {"days": 90}},
        ]
    )
    controller = RiskController(config)
    position = {
        "code": "AAA",
        "cost": 10.0,
        "entry_date": date(2026, 1, 1),
        "as_of_date": date(2026, 1, 30),
        "stop_loss_profile": "fixed_8",
    }

    result = controller.check_position(position, 9.1)

    assert result is not None
    assert result.source == "stop_loss"
