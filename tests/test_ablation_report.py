"""Ablation report formatting tests."""

from datetime import date
from types import SimpleNamespace

from src.backtest.ablation_config import (
    PREFERRED_QUARTER_HOLD_DAYS,
    get_ablation_experiments,
)
from src.backtest.ablation_report import (
    build_market_volatility_segments,
    format_ablation_report,
    format_candidate_comparison_report,
    format_high_vol_reentry_cooldown_report,
    format_high_vol_reentry_stop_price_report,
    format_reentry_rules_report,
    format_segmented_stop_loss_report,
    format_trend_reentry_segments_report,
)
from src.backtest.portfolio_backtest import TradeLog


def test_format_ablation_report_shows_baseline_deltas_and_stats():
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "default",
            "baseline_name": "baseline_full_gate",
        },
        "versions": {
            "baseline_full_gate": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "1",
                },
                "stats": {"premium_blocked": 2, "market_blocked": 3},
                "experiment": {"label": "Baseline 全门控"},
                "trades": [
                    TradeLog("AAA", date(2026, 1, 2), "建仓", 10.0, 100, 0.0, 100000, 99000, "v"),
                    TradeLog("AAA", date(2026, 1, 8), "SELL", 11.0, 100, 0.0, 99000, 100100, "v"),
                ],
            },
            "no_market_gate": {
                "summary": {
                    "annual_return": "12.00%",
                    "max_drawdown": "22.00%",
                    "win_rate": "55.00%",
                    "profit_factor": "1.7000",
                    "total_trades": "2",
                },
                "stats": {"premium_blocked": 1, "market_blocked": 0},
                "experiment": {"label": "关闭市场门控"},
                "trades": [],
            },
        },
    }

    report = format_ablation_report(result)

    assert "因子消融实验报告" in report
    assert "Baseline 全门控" in report
    assert "关闭市场门控" in report
    assert "+2.00%" in report
    assert "-2.00%" in report
    assert "溢价拦截" in report
    assert "市场拦截" in report


def test_preferred_cycle_matrix_uses_90_day_holding_limit():
    experiments, baseline_name = get_ablation_experiments("preferred-cycle")

    assert baseline_name == "preferred_baseline_full_gate"
    assert len(experiments) > 1
    assert {exp.max_holding_days for exp in experiments} == {PREFERRED_QUARTER_HOLD_DAYS}
    assert {exp.cycle_profile.name for exp in experiments} == {"monthly_quarter_90d"}


def test_format_ablation_report_marks_preferred_cycle_matrix():
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "preferred-cycle",
            "baseline_name": "preferred_baseline_full_gate",
        },
        "versions": {
            "preferred_baseline_full_gate": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "1",
                },
                "stats": {},
                "experiment": {"label": "周期Baseline 全门控"},
                "trades": [],
            },
        },
    }

    report = format_ablation_report(result)

    assert "实验集: preferred-cycle" in report
    assert "最长 90 个自然日持有约束" in report


def test_add_rules_matrix_uses_preferred_cycle_and_add_rule_variants():
    experiments, baseline_name = get_ablation_experiments("add-rules")

    assert baseline_name == "preferred_add_baseline"
    assert {exp.max_holding_days for exp in experiments} == {PREFERRED_QUARTER_HOLD_DAYS}
    assert {exp.add_rule.name for exp in experiments} == {
        "baseline",
        "disabled",
        "profit_only",
        "profit_score60",
        "pyramid_50",
        "pyramid_33",
    }


def test_entry_add_budget_matrix_uses_budget_rule_variants():
    experiments, baseline_name = get_ablation_experiments("entry-add-budget")

    assert baseline_name == "budget_100_no_add"
    assert {exp.max_holding_days for exp in experiments} == {PREFERRED_QUARTER_HOLD_DAYS}
    assert {exp.entry_add_budget_rule.name for exp in experiments} == {
        "budget_100_no_add",
        "budget_80_20_profit",
        "budget_80_20_score60",
        "budget_80_10_10_ladder",
        "budget_70_30_profit",
        "budget_70_15_15_ladder",
    }


def test_stop_loss_rules_matrix_uses_70_15_15_budget_rule():
    experiments, baseline_name = get_ablation_experiments("stop-loss-rules")

    assert baseline_name == "stop_fixed_8"
    assert {exp.max_holding_days for exp in experiments} == {PREFERRED_QUARTER_HOLD_DAYS}
    assert {exp.entry_add_budget_rule.name for exp in experiments} == {"budget_70_15_15_ladder"}
    assert {exp.stop_loss_rule.name for exp in experiments} == {
        "stop_none",
        "stop_fixed_6",
        "stop_fixed_8",
        "stop_fixed_10",
        "stop_fixed_12",
        "stop_atr_2_0",
        "stop_atr_2_5",
        "stop_atr_3_0",
    }


def test_candidate_comparison_matrix_contains_baseline_and_two_candidates():
    experiments, baseline_name = get_ablation_experiments("candidate-comparison")

    assert baseline_name == "baseline_v2_3_gate_lite_regime"
    assert [exp.name for exp in experiments] == [
        "baseline_v2_3_gate_lite_regime",
        "candidate_70_15_15_fixed8",
        "candidate_70_15_15_segment_stop",
    ]
    assert experiments[0].entry_add_budget_rule is None
    assert experiments[1].entry_add_budget_rule.name == "budget_70_15_15_ladder"
    assert experiments[1].max_holding_days == PREFERRED_QUARTER_HOLD_DAYS
    assert experiments[2].use_config_stop_loss_profiles is True


def test_reentry_rules_matrix_uses_v2_4_baseline():
    experiments, baseline_name = get_ablation_experiments("reentry-rules")

    assert baseline_name == "baseline_v2_4_segment_stop"
    assert experiments[0].name == "baseline_v2_4_segment_stop"
    assert experiments[0].reentry_rule is None
    assert {exp.entry_add_budget_rule.name for exp in experiments} == {"budget_70_15_15_ladder"}
    assert {exp.use_config_stop_loss_profiles for exp in experiments} == {True}
    assert {exp.max_holding_days for exp in experiments} == {PREFERRED_QUARTER_HOLD_DAYS}
    assert {exp.reentry_rule.name for exp in experiments[1:]} == {
        "reentry_cooldown_10",
        "reentry_cooldown_20",
        "reentry_score_60",
        "reentry_score_65",
        "reentry_price_reclaim",
        "reentry_trend_repair",
        "reentry_composite",
    }


def test_trend_reentry_segments_matrix_only_compares_v2_4_and_trend_repair():
    experiments, baseline_name = get_ablation_experiments("trend-reentry-segments")

    assert baseline_name == "baseline_v2_4_segment_stop"
    assert [exp.name for exp in experiments] == [
        "baseline_v2_4_segment_stop",
        "candidate_v2_5_trend_reentry",
    ]
    assert experiments[0].reentry_rule is None
    assert experiments[1].reentry_rule.name == "reentry_trend_repair"
    assert {exp.use_config_stop_loss_profiles for exp in experiments} == {True}


def test_high_vol_reentry_cooldown_matrix_uses_scoped_cooldown_rules():
    experiments, baseline_name = get_ablation_experiments("high-vol-reentry-cooldown")

    assert baseline_name == "baseline_v2_4_segment_stop"
    assert experiments[0].name == "baseline_v2_4_segment_stop"
    assert experiments[0].reentry_rule is None
    assert {exp.reentry_rule.name for exp in experiments[1:]} == {
        "reentry_high_vol_cooldown_10t",
        "reentry_high_vol_cooldown_15t",
        "reentry_high_vol_cooldown_20t",
        "reentry_high_vol_cooldown_30t",
        "reentry_a_high_vol_cooldown_20t",
        "reentry_low_vol_cooldown_20t",
    }
    main_rule = next(
        exp.reentry_rule
        for exp in experiments
        if exp.name == "reentry_high_vol_cooldown_20t"
    )
    assert main_rule.cooldown_trading_days == 20
    assert main_rule.volatility_groups == ("high_vol",)


def test_format_ablation_report_shows_add_rule_stats():
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "add-rules",
            "baseline_name": "preferred_add_baseline",
        },
        "versions": {
            "preferred_add_baseline": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "1",
                },
                "stats": {"add_executed": 2, "add_shares_total": 3000, "add_rule_blocked": 1},
                "experiment": {"label": "加仓Baseline"},
                "trades": [],
            },
        },
    }

    report = format_ablation_report(result)

    assert "加仓" in report
    assert "均加份额" in report
    assert "加仓过滤" in report
    assert "add-rules 实验集" in report


def test_format_ablation_report_marks_entry_add_budget_matrix():
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "entry-add-budget",
            "baseline_name": "budget_100_no_add",
        },
        "versions": {
            "budget_100_no_add": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "1",
                },
                "stats": {},
                "experiment": {"label": "100%建仓不加"},
                "trades": [],
            },
        },
    }

    report = format_ablation_report(result)

    assert "实验集: entry-add-budget" in report
    assert "比较建仓/加仓资金分配" in report


def test_format_ablation_report_marks_stop_loss_rules_matrix():
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "stop-loss-rules",
            "baseline_name": "stop_fixed_8",
        },
        "versions": {
            "stop_fixed_8": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "1",
                },
                "stats": {"stop_loss_triggered": 2, "max_holding_exit": 3},
                "experiment": {"label": "固定-8%"},
                "trades": [],
            },
        },
    }

    report = format_ablation_report(result)

    assert "实验集: stop-loss-rules" in report
    assert "只比较止损规则" in report
    assert "止损" in report
    assert "90日退出" in report


def test_build_market_volatility_segments_groups_by_market_and_atr():
    etfs = [
        SimpleNamespace(symbol="AAA", name="A1", regime_group="A股", market="A股"),
        SimpleNamespace(symbol="BBB", name="A2", regime_group="A股", market="A股"),
        SimpleNamespace(symbol="CCC", name="US", regime_group="美股", market="美股"),
    ]

    segments = build_market_volatility_segments(
        etf_items=etfs,
        codes=["AAA", "BBB", "CCC"],
        median_atr_by_code={"AAA": 0.02, "BBB": 0.03, "CCC": 0.01},
        atr_threshold=0.025,
    )

    by_name = {segment["name"]: segment for segment in segments}
    assert [item["symbol"] for item in by_name["A股_low_vol"]["etfs"]] == ["AAA"]
    assert [item["symbol"] for item in by_name["A股_high_vol"]["etfs"]] == ["BBB"]
    assert [item["symbol"] for item in by_name["美股_low_vol"]["etfs"]] == ["CCC"]
    assert by_name["美股_low_vol"]["sample_warning"] is True


def test_format_segmented_stop_loss_report_marks_best_by_calmar():
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA", "BBB"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "stop-loss-by-segment",
            "atr_threshold": 0.025,
            "baseline_name": "stop_fixed_8",
        },
        "segments": [
            {
                "name": "A股_high_vol",
                "market": "A股",
                "vol_group": "high_vol",
                "sample_warning": True,
                "etfs": [
                    {"symbol": "AAA", "name": "A1", "market": "A股", "median_atr_pct": 0.03},
                ],
                "best_name": "stop_fixed_10",
                "result": {
                    "versions": {
                        "stop_fixed_8": {
                            "summary": {
                                "annual_return": "8.00%",
                                "max_drawdown": "20.00%",
                                "calmar": "0.4000",
                                "win_rate": "40.00%",
                                "profit_factor": "1.2000",
                                "total_trades": "2",
                            },
                            "stats": {"stop_loss_triggered": 3, "max_holding_exit": 1},
                            "experiment": {"label": "固定-8%"},
                            "trades": [],
                        },
                        "stop_fixed_10": {
                            "summary": {
                                "annual_return": "9.00%",
                                "max_drawdown": "15.00%",
                                "calmar": "0.6000",
                                "win_rate": "45.00%",
                                "profit_factor": "1.5000",
                                "total_trades": "2",
                            },
                            "stats": {"stop_loss_triggered": 2, "max_holding_exit": 2},
                            "experiment": {"label": "固定-10%"},
                            "trades": [],
                        },
                    }
                },
            }
        ],
    }

    report = format_segmented_stop_loss_report(result)

    assert "分市场/分波动 ETF 止损消融实验报告" in report
    assert "A股_high_vol" in report
    assert "样本不足" in report
    assert "固定-10%" in report
    assert "BEST" in report


def test_format_candidate_comparison_report_shows_two_windows_and_deltas():
    window = {
        "meta": {
            "window": "2016-2026",
            "start": "2016-01-01",
            "end": "2026-06-05",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "candidate-comparison",
            "baseline_name": "baseline_v2_3_gate_lite_regime",
        },
        "versions": {
            "baseline_v2_3_gate_lite_regime": {
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
                "experiment": {"label": "baseline-v2.3"},
                "trades": [],
            },
            "candidate_70_15_15_segment_stop": {
                "summary": {
                    "annual_return": "12.00%",
                    "max_drawdown": "18.00%",
                    "calmar": "0.6667",
                    "sharpe": "0.7000",
                    "win_rate": "55.00%",
                    "profit_factor": "1.7000",
                    "total_trades": "2",
                },
                "stats": {"add_executed": 1, "stop_loss_triggered": 2, "max_holding_exit": 3},
                "experiment": {"label": "B 分段止损"},
                "trades": [],
            },
        },
    }
    result = {
        "meta": {
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "candidate-comparison",
            "baseline_name": "baseline_v2_3_gate_lite_regime",
        },
        "windows": [
            window,
            {**window, "meta": {**window["meta"], "window": "2024-2026", "start": "2024-01-01"}},
        ],
    }

    report = format_candidate_comparison_report(result)

    assert "候选策略对比实验报告" in report
    assert "区间: 2016-2026" in report
    assert "区间: 2024-2026" in report
    assert "B 分段止损" in report
    assert "+2.00%" in report
    assert "分市场/分波动止损 profile" in report


def test_format_reentry_rules_report_shows_reentry_metrics():
    window = {
        "meta": {
            "window": "2016-2026",
            "start": "2016-01-01",
            "end": "2026-06-05",
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "reentry-rules",
            "baseline_name": "baseline_v2_4_segment_stop",
        },
        "versions": {
            "baseline_v2_4_segment_stop": {
                "summary": {
                    "annual_return": "10.00%",
                    "max_drawdown": "20.00%",
                    "calmar": "0.5000",
                    "sharpe": "0.6000",
                    "win_rate": "50.00%",
                    "profit_factor": "1.5000",
                    "total_trades": "2",
                },
                "stats": {
                    "reentry_attempts": 4,
                    "reentry_allowed": 4,
                    "reentry_blocked": 0,
                    "reentry_executed": 3,
                    "reentry_closed": 2,
                    "reentry_wins": 1,
                    "reentry_pnl_pct_total": 0.04,
                    "reentry_stop_loss_exit": 1,
                },
                "experiment": {"label": "baseline-v2.4"},
                "trades": [],
            },
            "reentry_score_60": {
                "summary": {
                    "annual_return": "12.00%",
                    "max_drawdown": "18.00%",
                    "calmar": "0.6667",
                    "sharpe": "0.7000",
                    "win_rate": "55.00%",
                    "profit_factor": "1.7000",
                    "total_trades": "2",
                },
                "stats": {
                    "reentry_attempts": 4,
                    "reentry_allowed": 2,
                    "reentry_blocked": 2,
                    "reentry_executed": 2,
                    "reentry_closed": 2,
                    "reentry_wins": 2,
                    "reentry_pnl_pct_total": 0.10,
                    "reentry_stop_loss_exit": 0,
                },
                "experiment": {"label": "score>=60"},
                "trades": [],
            },
        },
    }
    result = {
        "meta": {
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "reentry-rules",
            "baseline_name": "baseline_v2_4_segment_stop",
        },
        "windows": [window],
    }

    report = format_reentry_rules_report(result)

    assert "止损后再入场规则消融实验报告" in report
    assert "baseline-v2.4" in report
    assert "score>=60" in report
    assert "再试" in report
    assert "再胜率" in report
    assert "100.00%" in report


def test_format_trend_reentry_segments_report_shows_segment_comparison():
    result = {
        "meta": {
            "codes": ["AAA", "BBB"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "trend-reentry-segments",
            "baseline_name": "baseline_v2_4_segment_stop",
        },
        "windows": [
            {
                "label": "2016-2026",
                "start": "2016-01-01",
                "end": "2026-06-05",
                "segments": [
                    {
                        "name": "全池",
                        "label": "全部 ETF",
                        "codes": ["AAA", "BBB"],
                        "etfs": [],
                        "sample_warning": False,
                        "result": {
                            "versions": {
                                "baseline_v2_4_segment_stop": {
                                    "summary": {
                                        "annual_return": "10.00%",
                                        "max_drawdown": "20.00%",
                                        "calmar": "0.5000",
                                        "win_rate": "50.00%",
                                    },
                                    "stats": {},
                                    "experiment": {"label": "baseline-v2.4"},
                                    "trades": [],
                                },
                                "candidate_v2_5_trend_reentry": {
                                    "summary": {
                                        "annual_return": "9.50%",
                                        "max_drawdown": "18.00%",
                                        "calmar": "0.5278",
                                        "win_rate": "49.00%",
                                    },
                                    "stats": {
                                        "reentry_executed": 2,
                                        "reentry_closed": 2,
                                        "reentry_wins": 1,
                                        "reentry_stop_loss_exit": 0,
                                    },
                                    "experiment": {"label": "趋势修复"},
                                    "trades": [],
                                },
                            }
                        },
                    }
                ],
            }
        ],
    }

    report = format_trend_reentry_segments_report(result)

    assert "趋势修复再入场分组验证报告" in report
    assert "全池" in report
    assert "趋势修复" in report
    assert "推荐" in report
    assert "分组 ETF" in report


def test_format_high_vol_reentry_cooldown_report_shows_segment_matrix():
    result = {
        "meta": {
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "high-vol-reentry-cooldown",
            "baseline_name": "baseline_v2_4_segment_stop",
        },
        "windows": [
            {
                "label": "2016-2026",
                "start": "2016-01-01",
                "end": "2026-06-05",
                "segments": [
                    {
                        "name": "A股高波动",
                        "label": "A股 high_vol",
                        "codes": ["AAA"],
                        "etfs": [],
                        "sample_warning": True,
                        "result": {
                            "versions": {
                                "baseline_v2_4_segment_stop": {
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
                                    "experiment": {"label": "baseline-v2.4"},
                                    "trades": [],
                                },
                                "reentry_high_vol_cooldown_20t": {
                                    "summary": {
                                        "annual_return": "11.00%",
                                        "max_drawdown": "18.00%",
                                        "calmar": "0.6111",
                                        "sharpe": "0.7000",
                                        "win_rate": "55.00%",
                                        "profit_factor": "1.7000",
                                        "total_trades": "2",
                                    },
                                    "stats": {
                                        "reentry_attempts": 3,
                                        "reentry_allowed": 1,
                                        "reentry_blocked": 2,
                                        "reentry_executed": 1,
                                        "reentry_closed": 1,
                                        "reentry_wins": 1,
                                        "reentry_pnl_pct_total": 0.05,
                                        "reentry_stop_loss_exit": 0,
                                    },
                                    "experiment": {"label": "高波20T"},
                                    "trades": [],
                                },
                            }
                        },
                    }
                ],
            }
        ],
    }

    report = format_high_vol_reentry_cooldown_report(result)

    assert "高波动 ETF 止损后再入场冷静期实验报告" in report
    assert "A股高波动" in report
    assert "高波20T" in report
    assert "+1.00%" in report
    assert "分组 ETF" in report


def test_high_vol_reentry_stop_price_matrix_scopes_rules():
    experiments, baseline_name = get_ablation_experiments("high-vol-reentry-stop-price")

    assert baseline_name == "baseline_v2_4_segment_stop"
    assert [exp.name for exp in experiments] == [
        "baseline_v2_4_segment_stop",
        "reentry_high_vol_price_above_stop",
        "reentry_a_high_vol_price_above_stop",
        "reentry_low_vol_price_above_stop",
    ]
    assert experiments[1].reentry_rule.require_price_above_stop_price is True
    assert experiments[1].reentry_rule.volatility_groups == ("high_vol",)
    assert experiments[2].reentry_rule.regime_groups == ("A股",)
    assert experiments[3].reentry_rule.volatility_groups == ("low_vol",)


def test_format_high_vol_reentry_stop_price_report_shows_segment_matrix():
    result = {
        "meta": {
            "codes": ["AAA"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
            "matrix": "high-vol-reentry-stop-price",
            "baseline_name": "baseline_v2_4_segment_stop",
        },
        "windows": [
            {
                "label": "2016-2026",
                "start": "2016-01-01",
                "end": "2026-06-05",
                "segments": [
                    {
                        "name": "A股高波动",
                        "label": "A股 high_vol",
                        "codes": ["AAA"],
                        "etfs": [],
                        "sample_warning": True,
                        "result": {
                            "versions": {
                                "baseline_v2_4_segment_stop": {
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
                                    "experiment": {"label": "baseline-v2.4"},
                                    "trades": [],
                                },
                                "reentry_high_vol_price_above_stop": {
                                    "summary": {
                                        "annual_return": "11.00%",
                                        "max_drawdown": "18.00%",
                                        "calmar": "0.6111",
                                        "sharpe": "0.7000",
                                        "win_rate": "55.00%",
                                        "profit_factor": "1.7000",
                                        "total_trades": "2",
                                    },
                                    "stats": {
                                        "reentry_attempts": 3,
                                        "reentry_allowed": 1,
                                        "reentry_blocked": 2,
                                        "reentry_executed": 1,
                                        "reentry_closed": 1,
                                        "reentry_wins": 1,
                                        "reentry_pnl_pct_total": 0.05,
                                        "reentry_stop_loss_exit": 0,
                                    },
                                    "experiment": {"label": "高波止损价"},
                                    "trades": [],
                                },
                            }
                        },
                    }
                ],
            }
        ],
    }

    report = format_high_vol_reentry_stop_price_report(result)

    assert "高波动 ETF 止损价再入场约束实验报告" in report
    assert "A股高波动" in report
    assert "高波止损价" in report
    assert "+1.00%" in report
    assert "低波止损价是反证组" in report
