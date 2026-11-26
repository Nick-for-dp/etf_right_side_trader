"""Volatility strategy experiment tests."""

from datetime import date

from src.backtest.ablation_config import (
    BUDGET_RULE_70_15_15_LADDER,
    VOL_HIGH_STRICT,
    VOL_LOW_LENIENT_ADD,
    AblationExperimentConfig,
    volatility_strategy_no_risk_experiments,
    volatility_strategy_production_experiments,
)
from src.backtest.portfolio_backtest import PortfolioBacktest, Position
from src.backtest.volatility_strategy_report import format_volatility_strategy_report
from src.backtest.volatility_strategy_report import _build_volatility_segments


class _Calendar:
    def __init__(self, days: list[str]):
        self.days = days

    def get_next_trading_day(self, day: str):
        idx = self.days.index(day)
        if idx + 1 >= len(self.days):
            return None
        return self.days[idx + 1]

    def get_trading_days_in_range(self, start, end):
        return self.days

    def get_previous_trading_day(self):
        return self.days[-1]


def test_volatility_strategy_layers_have_required_controls():
    no_risk = volatility_strategy_no_risk_experiments()
    production = volatility_strategy_production_experiments()

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
    assert all(candidate.volatility_strategy_rules for candidate in candidates)


def test_high_vol_entry_score_filter_blocks_only_target_group():
    bt = PortfolioBacktest(
        calendar=_Calendar(["2026-01-01"]),
        code_volatility_groups={"AAA": "high_vol", "BBB": "low_vol"},
    )
    experiment = AblationExperimentConfig(
        name="high",
        label="高波严格",
        volatility_strategy_rules=(VOL_HIGH_STRICT,),
    )
    stats = {}

    blocked = bt._volatility_entry_allows_advice(
        {"code": "AAA", "advice": "建仓", "signal_meta": {"score": 55}},
        experiment,
        stats,
    )
    ignored = bt._volatility_entry_allows_advice(
        {"code": "BBB", "advice": "建仓", "signal_meta": {"score": 55}},
        experiment,
        stats,
    )

    assert blocked is False
    assert ignored is True
    assert stats["vol_entry_candidates"] == 1
    assert stats["vol_entry_blocked"] == 1


def test_volatility_add_score_override_keeps_budget_profit_rule():
    bt = PortfolioBacktest(
        calendar=_Calendar(["2026-01-01"]),
        code_volatility_groups={"AAA": "low_vol", "BBB": "high_vol"},
    )
    low_experiment = AblationExperimentConfig(
        name="low",
        label="低波宽加",
        entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
        volatility_strategy_rules=(VOL_LOW_LENIENT_ADD,),
    )
    high_experiment = AblationExperimentConfig(
        name="high",
        label="高波严格",
        entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
        volatility_strategy_rules=(VOL_HIGH_STRICT,),
    )

    low_pos = Position(
        code="AAA",
        shares=1000,
        cost=10_000,
        entry_date=date(2026, 1, 1),
        target_budget=20_000,
        used_budget=10_000,
    )
    high_pos = Position(
        code="BBB",
        shares=1000,
        cost=10_000,
        entry_date=date(2026, 1, 1),
        target_budget=20_000,
        used_budget=10_000,
    )

    low_stats = {}
    high_stats = {}
    low_allowed = bt._budget_add_rule_allows_trade(
        low_pos,
        exec_price=10.5,
        signal_meta={"score": 56},
        experiment=low_experiment,
        stats=low_stats,
    )
    high_allowed = bt._budget_add_rule_allows_trade(
        high_pos,
        exec_price=10.5,
        signal_meta={"score": 65},
        experiment=high_experiment,
        stats=high_stats,
    )

    assert low_allowed is True
    assert low_stats["vol_add_allowed"] == 1
    assert high_allowed is False
    assert high_stats["vol_add_blocked"] == 1


def test_format_volatility_strategy_report_shows_two_layers():
    layer = {
        "versions": {
            "control_no_risk": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "calmar": "0.5000",
                    "sharpe": "0.6000",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "2",
                },
                "stats": {},
                "experiment": {"label": "对照无风控"},
            },
            "vol_high_strict_no_risk": {
                "summary": {
                    "annual_return": "12.00%",
                    "max_drawdown": "18.00%",
                    "calmar": "0.6667",
                    "sharpe": "0.7000",
                    "win_rate": "55.00%",
                    "profit_factor": "1.7000",
                    "total_trades": "2",
                },
                "stats": {"vol_entry_candidates": 3, "vol_entry_blocked": 1},
                "experiment": {"label": "高波严格"},
            },
        }
    }
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
        },
        "no_risk": layer,
        "production": {
            **layer,
            "versions": {
                "baseline_v2_4_segment_stop": layer["versions"]["control_no_risk"],
                "vol_high_strict_prod": layer["versions"]["vol_high_strict_no_risk"],
            },
        },
    }

    report = format_volatility_strategy_report(result)

    assert "高低波动 ETF 差异化策略实验报告" in report
    assert "第一层" in report
    assert "第二层" in report
    assert "高波严格" in report
    assert "入场拦截" in report


def test_build_volatility_segments_uses_config_groups():
    from types import SimpleNamespace

    etfs = [
        SimpleNamespace(symbol="AAA", name="A1", regime_group="A股", volatility_group="high_vol"),
        SimpleNamespace(symbol="BBB", name="A2", regime_group="A股", volatility_group="low_vol"),
        SimpleNamespace(symbol="CCC", name="US", regime_group="美股", volatility_group="high_vol"),
    ]

    segments = _build_volatility_segments(etfs, {"AAA", "BBB", "CCC"})
    by_name = {segment["name"]: segment for segment in segments}

    assert by_name["全池"]["codes"] == ["AAA", "BBB", "CCC"]
    assert by_name["高波动"]["codes"] == ["AAA", "CCC"]
    assert by_name["低波动"]["codes"] == ["BBB"]
    assert by_name["A股高波动"]["codes"] == ["AAA"]
    assert by_name["低波动"]["sample_warning"] is True
