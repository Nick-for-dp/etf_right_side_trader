"""Relative-strength backtest experiment tests."""

import pytest

from src.backtest.ablation_config import (
    relative_strength_no_risk_experiments,
    relative_strength_production_experiments,
)
from src.backtest.relative_strength import (
    apply_relative_strength_rule,
    relative_strength_score,
)


def test_relative_strength_layers_have_required_controls():
    no_risk = relative_strength_no_risk_experiments()
    production = relative_strength_production_experiments()

    control = no_risk[0]
    assert control.name == "control_no_risk"
    assert control.use_stop_loss is False
    assert control.max_holding_days is None
    assert control.entry_add_budget_rule is not None
    assert control.entry_add_budget_rule.entry_ratio == 0.7

    baseline = production[0]
    assert baseline.name == "baseline_v2_4_segment_stop"
    assert baseline.use_stop_loss is True
    assert baseline.max_holding_days == 90
    assert baseline.use_config_stop_loss_profiles is True
    assert baseline.entry_add_budget_rule is not None
    assert baseline.entry_add_budget_rule.entry_ratio == 0.7

    candidates = production[1:]
    assert all(candidate.use_stop_loss is True for candidate in candidates)
    assert all(candidate.max_holding_days == 90 for candidate in candidates)
    assert all(candidate.use_config_stop_loss_profiles is True for candidate in candidates)
    assert all(candidate.relative_strength_rule is not None for candidate in candidates)


def test_relative_strength_score_uses_weighted_returns():
    rule = relative_strength_no_risk_experiments()[1].relative_strength_rule
    assert rule is not None
    price_map = {
        "AAA": {
            "2026-01-01": 100.0,
            "2026-01-02": 110.0,
            "2026-01-03": 120.0,
            "2026-01-04": 140.0,
        }
    }
    rule = rule.__class__(
        name=rule.name,
        label=rule.label,
        windows=(1, 2, 3),
        weights=(0.5, 0.3, 0.2),
    )

    score = relative_strength_score("AAA", "2026-01-04", price_map, rule)

    expected = (
        (140.0 / 120.0 - 1.0) * 0.5
        + (140.0 / 110.0 - 1.0) * 0.3
        + (140.0 / 100.0 - 1.0) * 0.2
    )
    assert score == pytest.approx(expected)


def test_relative_strength_top_quantile_filters_weak_buy_signals():
    rule = relative_strength_no_risk_experiments()[3].relative_strength_rule
    assert rule is not None
    rule = rule.__class__(
        name=rule.name,
        label=rule.label,
        mode="filter",
        windows=(1,),
        weights=(1.0,),
        top_quantile=0.5,
    )
    price_map = {
        "AAA": {"2026-01-01": 100.0, "2026-01-02": 130.0},
        "BBB": {"2026-01-01": 100.0, "2026-01-02": 110.0},
        "CCC": {"2026-01-01": 100.0, "2026-01-02": 90.0},
    }
    rows = [
        {"code": "AAA", "date": "2026-01-02", "signal": "BUY", "signal_meta": {}},
        {"code": "BBB", "date": "2026-01-02", "signal": "BUY", "signal_meta": {}},
        {"code": "CCC", "date": "2026-01-02", "signal": "BUY", "signal_meta": {}},
        {"code": "DDD", "date": "2026-01-02", "signal": "SELL", "signal_meta": {}},
    ]

    filtered, stats = apply_relative_strength_rule(
        "2026-01-02",
        rows,
        price_map,
        rule,
    )

    buy_codes = [row["code"] for row in filtered if row["signal"] == "BUY"]
    assert buy_codes == ["AAA", "BBB"]
    assert any(row["code"] == "DDD" for row in filtered)
    assert stats["rs_buy_candidates"] == 3
    assert stats["rs_buy_allowed"] == 2
    assert stats["rs_buy_blocked"] == 1
