"""Strategy profile configuration tests."""

from src.config.settings_reader import AppConfig, EtfItem, load_config
from src.strategy.factory import create_strategy
from src.strategy.multi_indicator_scoring import MultiIndicatorScoring


def test_load_config_accepts_high_vol_signal_and_budget_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "demo")
    monkeypatch.setenv("DB_USER", "user")
    monkeypatch.setenv("DB_PASSWORD", "pass")
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        """
etf_list:
  - symbol: AAA
    name: AAA
    volatility_group: high_vol
    stop_loss_profile: atr_2_5
database:
  driver: postgresql
strategy:
  type: multi_indicator_scoring
  params:
    weights:
      trend: 0.35
      macd: 0.25
      rsi: 0.15
      bb: 0.25
    thresholds:
      buy: 50
      sell: -50
    volatility_signal_profiles:
      high_vol:
        enabled: true
        kind: high_vol_balanced
    entry_budget_overrides:
      high_vol:
        enabled: true
        kind: quality_tier
        strong_score: 65
        strong_multiplier: 1.0
        medium_score: 55
        medium_multiplier: 0.8
        weak_multiplier: 0.6
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.strategy_params["volatility_signal_profiles"]["high_vol"] == {
        "enabled": True,
        "kind": "high_vol_balanced",
        "params": {},
    }
    assert config.strategy_params["entry_budget_overrides"]["high_vol"]["weak_multiplier"] == 0.6


def test_create_strategy_passes_volatility_profiles():
    config = AppConfig(
        etf_list=[EtfItem(symbol="AAA", volatility_group="high_vol")],
        db_url="postgresql://unused",
        strategy_type="multi_indicator_scoring",
        strategy_params={
            "weights": {"trend": 0.35, "macd": 0.25, "rsi": 0.15, "bb": 0.25},
            "thresholds": {"buy": 50, "sell": -50},
            "volatility_signal_profiles": {
                "high_vol": {"enabled": True, "kind": "high_vol_balanced"},
            },
        },
    )

    strategy = create_strategy(config)

    assert isinstance(strategy, MultiIndicatorScoring)
    assert strategy.version == "2.5"
    assert strategy.code_volatility_groups == {"AAA": "high_vol"}


def test_load_config_rejects_unknown_signal_profile_kind(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "demo")
    monkeypatch.setenv("DB_USER", "user")
    monkeypatch.setenv("DB_PASSWORD", "pass")
    config_file = tmp_path / "settings.yaml"
    config_file.write_text(
        """
etf_list:
  - symbol: BBB
    name: BBB
    volatility_group: low_vol
database:
  driver: postgresql
strategy:
  type: multi_indicator_scoring
  params:
    weights:
      trend: 0.35
      macd: 0.25
      rsi: 0.15
      bb: 0.25
    thresholds:
      buy: 50
      sell: -50
    volatility_signal_profiles:
      low_vol:
        enabled: true
        kind: relaxed_default
""",
        encoding="utf-8",
    )

    try:
        load_config(config_file)
    except ValueError as exc:
        assert "relaxed_default" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown profile kind")
