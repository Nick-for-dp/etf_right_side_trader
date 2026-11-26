"""市场热度服务单元测试。"""

from datetime import date, timedelta

from src.config.settings_reader import MarketIndexItem
from src.models import MarketIndexQuote, MarketState
from src.service.market_regime_service import (
    MarketRegimeService,
    build_per_code_market_regime,
    compute_single_index_regime,
)


def _index(code: str) -> MarketIndexItem:
    return MarketIndexItem(code=code, name=code, weight=1.0)


def _observe_index(code: str) -> MarketIndexItem:
    return MarketIndexItem(code=code, name=code, weight=0.0)


def _quotes(code: str, start: date, closes: list[float]) -> list[MarketIndexQuote]:
    rows = []
    for i, close in enumerate(closes):
        rows.append(MarketIndexQuote(
            index_code=code,
            date=start + timedelta(days=i),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000 + i * 10,
            amount=100000 + i * 1000,
        ))
    return rows


def test_market_regime_hot_when_indices_rise_with_consensus(monkeypatch):
    """多指数共振上涨且分数足够高时，输出 HOT。"""
    start = date(2026, 1, 1)
    target = start + timedelta(days=79)
    indices = [_index(f"idx{i}") for i in range(4)]
    close_series = [100 + i * 0.5 for i in range(80)]
    data = {idx.code: _quotes(idx.code, start, close_series) for idx in indices}

    monkeypatch.setattr(
        "src.service.market_regime_service.market_index_quote_repo.find_by_code_in_range",
        lambda code, _start, _end: data[code],
    )

    service = MarketRegimeService(indices, {
        "lookback_days": 120,
        "min_indices": 4,
        "hot_score": 0.45,
        "cold_score": -0.45,
        "hot_ratio": 0.5,
        "cold_ratio": 0.5,
    })
    regime = service.calculate(target)

    # HOT 状态因持续上涨被细分为 HOT_RISING
    assert regime.state in {MarketState.HOT.value, MarketState.HOT_RISING.value}
    assert regime.score is not None and regime.score > 0
    assert regime.data["valid_indices"] == 4


def test_market_regime_unknown_when_not_enough_indices(monkeypatch):
    """有效指数数量不足时，输出 UNKNOWN，不做硬判断。"""
    start = date(2026, 1, 1)
    target = start + timedelta(days=79)
    indices = [_index(f"idx{i}") for i in range(4)]
    data = {
        "idx0": _quotes("idx0", start, [100 + i * 0.1 for i in range(80)]),
        "idx1": _quotes("idx1", start, [100 + i * 0.1 for i in range(80)]),
    }

    monkeypatch.setattr(
        "src.service.market_regime_service.market_index_quote_repo.find_by_code_in_range",
        lambda code, _start, _end: data.get(code, []),
    )

    service = MarketRegimeService(indices, {
        "lookback_days": 120,
        "min_indices": 4,
    })
    regime = service.calculate(target)

    assert regime.state == MarketState.UNKNOWN.value
    assert regime.data["reason"] == "insufficient_index_data"
    assert regime.data["valid_indices"] == 2


def test_zero_weight_indices_do_not_satisfy_min_indices(monkeypatch):
    """观察指数有数据也不参与热度评分有效数量。"""
    start = date(2026, 1, 1)
    target = start + timedelta(days=79)
    indices = [_index("score0"), _index("score1"), _observe_index("observe0"), _observe_index("observe1")]
    close_series = [100 + i * 0.1 for i in range(80)]
    data = {idx.code: _quotes(idx.code, start, close_series) for idx in indices}

    monkeypatch.setattr(
        "src.service.market_regime_service.market_index_quote_repo.find_by_code_in_range",
        lambda code, _start, _end: data[code],
    )

    service = MarketRegimeService(indices, {
        "lookback_days": 120,
        "min_indices": 4,
    })
    regime = service.calculate(target)

    assert regime.state == MarketState.UNKNOWN.value
    assert regime.data["reason"] == "insufficient_index_data"
    assert regime.data["valid_indices"] == 2
    assert regime.data["observed_indices"] == 4


def test_single_index_regime_reuses_full_market_scoring(monkeypatch):
    """单指数 regime 应复用主 market_regime 评分和状态细分口径。"""
    start = date(2026, 1, 1)
    target = start + timedelta(days=79)
    closes = [100 + i * 0.5 for i in range(80)]
    data = {"NDX": _quotes("NDX", start, closes)}

    monkeypatch.setattr(
        "src.service.market_regime_service.market_index_quote_repo.find_by_code_in_range",
        lambda code, _start, _end: data.get(code, []),
    )

    params = {
        "lookback_days": 120,
        "min_indices": 1,
        "hot_score": 0.45,
        "cold_score": -0.45,
        "hot_ratio": 0.5,
        "cold_ratio": 0.5,
    }
    service_regime = MarketRegimeService([_index("NDX")], params).calculate(target)
    single_regime = compute_single_index_regime("NDX", target, params=params)

    assert single_regime["state"] == service_regime.state
    assert single_regime["score"] == service_regime.score
    assert single_regime["data"]["valid_indices"] == 1


def test_build_per_code_market_regime_uses_group_mapping(monkeypatch):
    """美股走 NDX 独立 regime；港股走 HZ5017 独立 regime。"""
    start = date(2026, 1, 1)
    target = start + timedelta(days=79)
    data = {
        "NDX": _quotes("NDX", start, [100 + i * 0.5 for i in range(80)]),
        "HZ5017": _quotes("HZ5017", start, [200 + i * 0.5 for i in range(80)]),
    }

    monkeypatch.setattr(
        "src.service.market_regime_service.market_index_quote_repo.find_by_code_in_range",
        lambda code, _start, _end: data.get(code, []),
    )

    base_regime = {"state": MarketState.BEAR_TREND.value, "score": -0.6}
    result = build_per_code_market_regime(
        {
            "US_ETF": "美股",
            "HK_ETF": "港股",
            "CN_ETF": "A股",
        },
        target,
        base_regime,
        params={
            "lookback_days": 120,
            "hot_score": 0.45,
            "cold_score": -0.45,
        },
    )

    assert result["US_ETF"]["state"] != base_regime["state"]
    assert result["HK_ETF"]["state"] != base_regime["state"]
    assert result["CN_ETF"] == base_regime
