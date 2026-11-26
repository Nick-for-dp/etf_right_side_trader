"""市场状态计算服务。

三态：RISK_OFF（拦截买入）/ NORMAL / UNKNOWN（数据不足，不拦截）。
细分原因（hot_rising / hot_falling / bear_trend / panic / recovery）
写入 market_regime.data.reason，仅作解释，不参与门控。
"""

from datetime import date, timedelta

import pandas as pd

from src.config.settings_reader import MarketIndexItem
from src.database import market_index_quote_repo, market_regime_repo

from src.models import MarketRegime, MarketState
from src.utils import get_logger

logger = get_logger(__name__)

_REGIME_GROUP_INDEX_CODE = {
    "美股": "NDX",
    "港股": "HZ5017",
}

# 细分原因 → 三态
_RISK_OFF_REASONS = {"hot_falling", "bear_trend", "panic"}
_REASON_STATE = {
    "hot_rising": MarketState.NORMAL,
    "hot_falling": MarketState.RISK_OFF,
    "bear_trend": MarketState.RISK_OFF,
    "panic": MarketState.RISK_OFF,
    "recovery": MarketState.NORMAL,
    "normal": MarketState.NORMAL,
}


class MarketRegimeService:
    """基于宽基指数日线计算全市场状态。"""

    def __init__(self, indices: list[MarketIndexItem], params: dict | None = None):
        self.indices = indices
        self.params = params or {}

    def calculate_and_save(self, target_date: date) -> MarketRegime:
        """计算并保存指定日期的市场状态。"""
        regime = self.calculate(target_date)
        market_regime_repo.save(regime)
        return regime

    def calculate(self, target_date: date) -> MarketRegime:
        """计算指定日期的市场状态，不写数据库。"""
        lookback_days = self.params.get("lookback_days", 180)
        fetch_start = target_date - timedelta(days=lookback_days)

        index_results = []
        for index in self.indices:
            quotes = market_index_quote_repo.find_by_code_in_range(
                index.code, fetch_start, target_date
            )
            result = _calculate_index_state(index, quotes, target_date)
            if result is not None:
                index_results.append(result)

        return _aggregate_index_results(index_results, target_date, self.params)


def _aggregate_index_results(
    index_results: list[dict],
    target_date: date,
    params: dict | None = None,
) -> MarketRegime:
    """聚合指数评分（HOT/COLD/NORMAL 为单指数热度标签），得到三态市场状态。"""
    params = params or {}
    scoring_results = [item for item in index_results if item["weight"] > 0]

    min_indices = params.get("min_indices", 4)
    if len(scoring_results) < min_indices:
        return _unknown_regime(
            target_date, "insufficient_index_data", index_results,
            valid_indices=len(scoring_results), min_indices=min_indices,
        )

    total_weight = sum(item["weight"] for item in scoring_results)
    if total_weight <= 0:
        return _unknown_regime(
            target_date, "no_positive_index_weight", index_results,
            valid_indices=len(scoring_results),
        )

    score = sum(item["score"] * item["weight"] for item in scoring_results) / total_weight
    hot_weight = sum(
        item["weight"] for item in scoring_results
        if item["state"] == "HOT"
    )
    cold_weight = sum(
        item["weight"] for item in scoring_results
        if item["state"] == "COLD"
    )

    hot_score = params.get("hot_score", 0.55)
    cold_score = params.get("cold_score", -0.55)
    hot_ratio = params.get("hot_ratio", 0.5)
    cold_ratio = params.get("cold_ratio", 0.5)

    if score >= hot_score and hot_weight / total_weight >= hot_ratio:
        base_state = "HOT"
    elif score <= cold_score and cold_weight / total_weight >= cold_ratio:
        base_state = "COLD"
    else:
        base_state = "NORMAL"

    reason = _refine_reason(base_state, scoring_results)
    state = _REASON_STATE[reason]

    return MarketRegime(
        date=target_date,
        state=state.value,
        score=round(score, 4),
        data={
            "reason": reason,
            "hot_weight_ratio": round(hot_weight / total_weight, 4),
            "cold_weight_ratio": round(cold_weight / total_weight, 4),
            "valid_indices": len(scoring_results),
            "observed_indices": len(index_results),
            "indices": index_results,
        },
    )


def _unknown_regime(
    target_date: date, reason: str, index_results: list[dict], **extra
) -> MarketRegime:
    return MarketRegime(
        date=target_date,
        state=MarketState.UNKNOWN.value,
        score=None,
        data={
            "reason": reason,
            "observed_indices": len(index_results),
            "indices": index_results,
            **extra,
        },
    )


def _refine_reason(base_state: str, scoring_results: list[dict]) -> str:
    """根据短期趋势方向和极端指标细分 HOT/COLD 的原因。"""
    if base_state == "HOT":
        recent_returns = [
            item["ret5"] for item in scoring_results
            if item.get("ret5") is not None
        ]
        avg_5d_return = sum(recent_returns) / len(recent_returns) if recent_returns else 0
        return "hot_rising" if avg_5d_return > 0 else "hot_falling"

    if base_state == "COLD":
        max_rsi = None
        for item in scoring_results:
            rsi = item.get("rsi")
            if rsi is not None and (max_rsi is None or rsi > max_rsi):
                max_rsi = rsi

        min_gap = None
        for item in scoring_results:
            gap = item.get("ma20_gap")
            if gap is not None and (min_gap is None or gap < min_gap):
                min_gap = gap

        if min_gap is not None and min_gap > -0.01:
            return "recovery"
        if max_rsi is not None and max_rsi < 20:
            return "panic"
        return "bear_trend"

    return "normal"


def _calculate_index_state(
    index: MarketIndexItem,
    quotes: list,
    target_date: date,
) -> dict | None:
    """计算单个指数在 target_date 的热度分。"""
    if not quotes:
        return None

    df = pd.DataFrame([{
        "date": q.date,
        "close": q.close,
        "volume": q.volume,
        "amount": q.amount,
    } for q in quotes]).sort_values("date").reset_index(drop=True)

    df = df[df["date"] <= target_date].copy()
    if df.empty or df.iloc[-1]["date"] != target_date or len(df) < 61:
        return None

    close = pd.to_numeric(df["close"], errors="coerce")
    activity_source = (
        pd.to_numeric(df["amount"], errors="coerce")
        if df["amount"].notna().sum() >= 20
        else pd.to_numeric(df["volume"], errors="coerce")
    )
    activity_name = "amount" if df["amount"].notna().sum() >= 20 else "volume"

    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    rsi = _rsi(close, 14)
    activity_ma20 = activity_source.rolling(20).mean()

    current = close.iloc[-1]
    ret5 = current / close.shift(5).iloc[-1] - 1.0
    ret20 = current / close.shift(20).iloc[-1] - 1.0
    ret60 = current / close.shift(60).iloc[-1] - 1.0
    ma20_val = ma20.iloc[-1]
    ma60_val = ma60.iloc[-1]
    rsi_val = rsi.iloc[-1]
    activity_ma20_val = activity_ma20.iloc[-1]
    activity_ratio = (
        activity_source.iloc[-1] / activity_ma20_val
        if pd.notna(activity_ma20_val) and activity_ma20_val != 0
        else pd.NA
    )

    if pd.isna(ret20) or pd.isna(ret60) or pd.isna(ma20_val) or pd.isna(ma60_val):
        return None

    trend_score = _trend_score(current, ma20_val, ma60_val)
    score = (
        0.25 * _clip(ret20 / 0.12) +
        0.20 * _clip(ret60 / 0.20) +
        0.20 * trend_score +
        0.20 * _clip((rsi_val - 50.0) / 25.0) +
        0.15 * _activity_score(activity_ratio, ret20)
    )

    if score >= 0.55:
        state = "HOT"
    elif score <= -0.55:
        state = "COLD"
    else:
        state = "NORMAL"

    return {
        "code": index.code,
        "name": index.name,
        "state": state,
        "score": round(float(score), 4),
        "weight": index.weight,
        "ret5": round(float(ret5), 6) if pd.notna(ret5) else None,
        "ret20": round(float(ret20), 6),
        "ret60": round(float(ret60), 6),
        "ma20_gap": round(float(current / ma20_val - 1.0), 6),
        "ma60_gap": round(float(current / ma60_val - 1.0), 6),
        "rsi": round(float(rsi_val), 4) if pd.notna(rsi_val) else None,
        "activity_ratio": round(float(activity_ratio), 4)
        if pd.notna(activity_ratio) else None,
        "activity_source": activity_name,
    }


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    result = 100 - (100 / (1 + rs))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return result


def _trend_score(close: float, ma20: float, ma60: float) -> float:
    if close > ma20 > ma60:
        return 1.0
    if close < ma20 < ma60:
        return -1.0
    return _clip(((close / ma20 - 1.0) + (ma20 / ma60 - 1.0)) / 0.08)


def _activity_score(activity_ratio: float, ret20: float) -> float:
    if pd.isna(activity_ratio):
        return 0.0
    direction = 1.0 if ret20 >= 0 else -1.0
    return _clip((activity_ratio - 1.0) / 0.8) * direction


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    if pd.isna(value):
        return 0.0
    return max(low, min(high, float(value)))


def compute_single_index_regime(
    index_code: str,
    target_date: date,
    lookback_days: int | None = None,
    params: dict | None = None,
) -> dict:
    """对单只指数按主 market_regime 口径计算独立市场状态。"""
    params = params or {}
    actual_lookback_days = lookback_days or params.get("lookback_days", 180)
    fetch_start = target_date - timedelta(days=actual_lookback_days)
    quotes = market_index_quote_repo.find_by_code_in_range(
        index_code, fetch_start, target_date
    )
    if not quotes:
        return {"state": MarketState.UNKNOWN.value, "score": None}

    index = MarketIndexItem(code=index_code, name=index_code, weight=1.0)
    index_result = _calculate_index_state(index, quotes, target_date)
    if index_result is None:
        return {"state": MarketState.UNKNOWN.value, "score": None}

    aggregate_params = dict(params)
    aggregate_params["min_indices"] = 1
    regime = _aggregate_index_results([index_result], target_date, aggregate_params)
    return {"state": regime.state, "score": regime.score, "data": regime.data}


def build_per_code_market_regime(
    code_regime_groups: dict[str, str],
    target_date: date,
    base_regime: dict | None,
    params: dict | None = None,
) -> dict[str, dict]:
    """按 ETF 的 regime_group 构建 per-code market_regime。

    美股 ETF 使用 NDX 独立 regime，港股 ETF 使用恒生科技 HZ5017
    独立 regime。未识别分组回退 base_regime，避免缺数据时误杀信号。
    """
    fallback = base_regime or {"state": MarketState.UNKNOWN.value}
    group_cache: dict[str, dict] = {}
    result: dict[str, dict] = {}

    for code, regime_group in code_regime_groups.items():
        index_code = _REGIME_GROUP_INDEX_CODE.get(regime_group)
        if not index_code:
            result[code] = fallback
            continue

        if regime_group not in group_cache:
            group_cache[regime_group] = compute_single_index_regime(
                index_code, target_date, params=params
            )
        result[code] = group_cache[regime_group]

    return result
