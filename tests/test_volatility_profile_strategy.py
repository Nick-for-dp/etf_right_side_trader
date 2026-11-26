"""Bottom-layer volatility profile strategy experiment tests."""

from datetime import date

import pandas as pd

from src.backtest.ablation_config import (
    SIGNAL_PROFILE_HIGH_VOL_BALANCED,
    SIGNAL_PROFILE_LOW_VOL_STABLE,
    high_vol_profile_strategy_experiments,
    low_vol_profile_strategy_experiments,
)
from src.backtest.experimental_signals import (
    _generate_high_vol_balanced,
    _generate_low_vol_stable,
)
from src.backtest.portfolio_backtest import (
    PortfolioBacktest,
    Position,
)
from src.backtest.volatility_profile_strategy_report import (
    format_volatility_profile_strategy_report,
)


def _row(**overrides) -> dict:
    data = {
        "code": "AAA",
        "date": "2026-01-02",
        "ma20": 10.2,
        "ma60": 10.0,
        "close": 10.5,
        "dif": 0.08,
        "dea": 0.04,
        "rsi": 58.0,
        "bb_upper": 10.8,
        "bb_lower": 9.8,
        "bb_mid": 10.3,
        "bb_width": 0.097,
        "adx14": 24.0,
        "vol_ratio": 1.15,
        "atr_pct": 0.03,
    }
    data.update(overrides)
    return data


def test_high_vol_profile_experiments_compare_baseline_signal_and_full_candidate():
    experiments = high_vol_profile_strategy_experiments()

    assert [exp.name for exp in experiments] == [
        "baseline_v2_4_segment_stop",
        "high_vol_signal_baseline_risk",
        "high_vol_signal_trend_risk",
    ]
    assert experiments[0].experimental_signal_profile is None
    assert experiments[1].experimental_signal_profile.name == "signal_high_vol_balanced"
    assert experiments[1].experimental_risk_profile is None
    assert experiments[2].experimental_risk_profile.name == "risk_high_vol_trend"
    assert experiments[2].max_holding_days is None


def test_low_vol_profile_experiments_compare_baseline_signal_and_full_candidate():
    experiments = low_vol_profile_strategy_experiments()

    assert [exp.name for exp in experiments] == [
        "baseline_v2_4_segment_stop",
        "low_vol_signal_baseline_risk",
        "low_vol_signal_structure_risk",
    ]
    assert experiments[1].experimental_signal_profile.name == "signal_low_vol_stable"
    assert experiments[2].experimental_risk_profile.name == "risk_low_vol_structure"
    assert experiments[2].max_holding_days == 180


def test_high_vol_balanced_profile_generates_buy_with_balanced_confirmation():
    df = pd.DataFrame([_row()])

    result = _generate_high_vol_balanced(df, SIGNAL_PROFILE_HIGH_VOL_BALANCED)

    assert result[0]["signal"] == "BUY"
    meta = result[0]["signal_meta"]
    assert meta["profile"] == "signal_high_vol_balanced"
    assert meta["s_trend"] > 0
    assert meta["s_rsi"] > 0
    assert meta["s_volume"] > 0


def test_low_vol_stable_profile_generates_buy_on_repair_structure():
    df = pd.DataFrame([
        _row(date="2026-01-01", close=10.25, rsi=48.0, vol_ratio=0.8),
        _row(date="2026-01-02", close=10.28, rsi=52.0, vol_ratio=0.85, dif=0.03, dea=0.025),
    ])

    result = _generate_low_vol_stable(df, SIGNAL_PROFILE_LOW_VOL_STABLE)

    assert result[-1]["signal"] == "BUY"
    meta = result[-1]["signal_meta"]
    assert meta["profile"] == "signal_low_vol_stable"
    assert meta["s_rsi"] > 0
    assert meta["s_pullback"] > 0


def test_experimental_high_vol_risk_triggers_trailing_stop():
    experiment = high_vol_profile_strategy_experiments()[2]
    pos = Position(
        code="AAA",
        shares=1000,
        cost=10_000,
        entry_date=date(2026, 1, 1),
        peak_price=11.0,
    )

    signal = PortfolioBacktest._experimental_risk_signal(
        pos=pos,
        close=10.5,
        pnl_pct=0.05,
        experiment=experiment,
        risk_info={"atr_pct": 0.02, "ma20": 10.3, "dif": 0.04, "dea": 0.03},
    )

    assert signal is not None
    assert signal["source"] == "trailing_stop"


def test_experimental_low_vol_risk_triggers_structure_exit():
    experiment = low_vol_profile_strategy_experiments()[2]
    pos = Position(
        code="AAA",
        shares=1000,
        cost=10_000,
        entry_date=date(2026, 1, 1),
        peak_price=10.5,
    )

    signal = PortfolioBacktest._experimental_risk_signal(
        pos=pos,
        close=9.8,
        pnl_pct=-0.02,
        experiment=experiment,
        risk_info={"ma20": 9.9, "ma60": 10.0, "dif": 0.01, "dea": 0.02},
    )

    assert signal is not None
    assert signal["source"] == "structure_exit"


def test_format_volatility_profile_strategy_report_shows_two_groups():
    version = {
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
    }
    result = {
        "meta": {
            "start": "2026-01-01",
            "end": "2026-01-10",
            "codes": ["AAA", "BBB"],
            "capital": 100000.0,
            "cost_ratio": 0.0005,
            "slippage": 0.0001,
            "position_limit": 0.3,
        },
        "groups": [
            {
                "name": "高波动",
                "codes": ["AAA"],
                "result": {
                    "versions": {
                        "baseline_v2_4_segment_stop": version,
                        "high_vol_signal_trend_risk": {
                            **version,
                            "experiment": {"label": "高波新信号+风控"},
                        },
                    }
                },
            },
            {
                "name": "低波动",
                "codes": ["BBB"],
                "result": {
                    "versions": {
                        "baseline_v2_4_segment_stop": version,
                    }
                },
            },
        ],
    }

    report = format_volatility_profile_strategy_report(result)

    assert "高低波动 ETF 底层策略分离消融实验报告" in report
    assert "分组: 高波动" in report
    assert "分组: 低波动" in report
    assert "高波新信号+风控" in report
