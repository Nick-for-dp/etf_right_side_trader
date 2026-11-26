"""Cross-sectional relative-strength helpers for backtest experiments."""

from bisect import bisect_right
from math import ceil
from typing import Any

from src.backtest.ablation_config import RelativeStrengthRuleConfig


def build_relative_strength_score_map(
    signal_rows: list[dict],
    price_map: dict[str, dict[str, float]],
    rule: RelativeStrengthRuleConfig,
    *,
    benchmark_price_map: dict[str, dict[str, float]] | None = None,
    code_benchmark_indices: dict[str, str] | None = None,
) -> dict[tuple[str, str], float | None]:
    """Precompute RS score by (date, code) for BUY signals."""
    dates_by_code = {
        code: sorted(prices)
        for code, prices in price_map.items()
    }
    benchmark_dates_by_code = {
        code: sorted(prices)
        for code, prices in (benchmark_price_map or {}).items()
    }

    score_map: dict[tuple[str, str], float | None] = {}
    seen: set[tuple[str, str]] = set()
    for row in signal_rows:
        if row.get("signal") != "BUY":
            continue
        key = (row["date"], row["code"])
        if key in seen:
            continue
        seen.add(key)
        score_map[key] = relative_strength_score(
            code=row["code"],
            day_str=row["date"],
            price_map=price_map,
            rule=rule,
            benchmark_price_map=benchmark_price_map,
            benchmark_index=(code_benchmark_indices or {}).get(row["code"]),
            dates_by_code=dates_by_code,
            benchmark_dates_by_code=benchmark_dates_by_code,
        )
    return score_map


def apply_relative_strength_rule(
    day_str: str,
    signal_rows: list[dict],
    price_map: dict[str, dict[str, float]],
    rule: RelativeStrengthRuleConfig,
    *,
    benchmark_price_map: dict[str, dict[str, float]] | None = None,
    code_benchmark_indices: dict[str, str] | None = None,
    score_map: dict[tuple[str, str], float | None] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Enrich or filter BUY rows by a cross-sectional RS rule.

    Non-BUY rows are always preserved. BUY rows with missing RS data are
    excluded only when the rule is a filter; rank mode keeps them but assigns
    no usable ordering score.
    """
    stats = {
        "rs_buy_candidates": 0,
        "rs_buy_allowed": 0,
        "rs_buy_blocked": 0,
        "rs_scores_missing": 0,
    }
    buy_rows = [row for row in signal_rows if row.get("signal") == "BUY"]
    other_rows = [row for row in signal_rows if row.get("signal") != "BUY"]
    if not buy_rows:
        return list(signal_rows), stats

    scored: list[tuple[dict, float | None]] = []
    for row in buy_rows:
        code = row["code"]
        score = (
            score_map.get((day_str, code))
            if score_map is not None
            else relative_strength_score(
                code=code,
                day_str=day_str,
                price_map=price_map,
                rule=rule,
                benchmark_price_map=benchmark_price_map,
                benchmark_index=(code_benchmark_indices or {}).get(code),
            )
        )
        stats["rs_buy_candidates"] += 1
        if score is None:
            stats["rs_scores_missing"] += 1
        enriched = dict(row)
        meta = dict(enriched.get("signal_meta", {}) or {})
        if score is not None:
            meta["rs_score"] = score
        meta["rs_rule"] = rule.name
        enriched["signal_meta"] = meta
        scored.append((enriched, score))

    if rule.mode == "filter":
        allowed_codes = _top_quantile_codes(scored, rule.top_quantile or 0.4)
        filtered = [
            row for row, score in scored
            if score is not None and row["code"] in allowed_codes
        ]
        stats["rs_buy_allowed"] = len(filtered)
        stats["rs_buy_blocked"] = len(buy_rows) - len(filtered)
        return other_rows + sort_by_relative_strength(filtered), stats

    ranked_rows = [row for row, _score in scored]
    stats["rs_buy_allowed"] = len(ranked_rows)
    return other_rows + sort_by_relative_strength(ranked_rows), stats


def sort_by_relative_strength(rows: list[dict]) -> list[dict]:
    """Sort executable BUY/ADD advices by descending RS score."""
    return sorted(
        rows,
        key=lambda row: _score_sort_key((row.get("signal_meta") or {}).get("rs_score")),
        reverse=True,
    )


def relative_strength_score(
    code: str,
    day_str: str,
    price_map: dict[str, dict[str, float]],
    rule: RelativeStrengthRuleConfig,
    *,
    benchmark_price_map: dict[str, dict[str, float]] | None = None,
    benchmark_index: str | None = None,
    dates_by_code: dict[str, list[str]] | None = None,
    benchmark_dates_by_code: dict[str, list[str]] | None = None,
) -> float | None:
    """Calculate weighted multi-window RS score for one ETF at one date."""
    code_prices = price_map.get(code, {})
    code_dates = (dates_by_code or {}).get(code)
    returns = [
        _window_return(code_prices, day_str, window, dates=code_dates)
        for window in rule.windows
    ]
    if any(value is None for value in returns):
        return None

    if rule.score_kind == "excess":
        if benchmark_price_map is None or benchmark_index is None:
            return None
        benchmark_prices = benchmark_price_map.get(benchmark_index, {})
        benchmark_dates = (benchmark_dates_by_code or {}).get(benchmark_index)
        benchmark_returns = [
            _window_return(benchmark_prices, day_str, window, dates=benchmark_dates)
            for window in rule.windows
        ]
        if any(value is None for value in benchmark_returns):
            return None
        returns = [
            etf_return - benchmark_return
            for etf_return, benchmark_return in zip(returns, benchmark_returns)
        ]

    weights = _normalized_weights(rule.weights, len(rule.windows))
    return sum(value * weight for value, weight in zip(returns, weights))


def market_benchmark_for_regime_group(regime_group: str) -> str:
    """Return the broad market benchmark used by RS excess experiments."""
    if regime_group == "美股":
        return "NDX"
    if regime_group == "港股":
        return "HZ5017"
    return "000300"


def _top_quantile_codes(
    scored: list[tuple[dict, float | None]],
    top_quantile: float,
) -> set[str]:
    valid = [(row, score) for row, score in scored if score is not None]
    if not valid:
        return set()
    keep = max(1, ceil(len(valid) * top_quantile))
    ordered = sorted(valid, key=lambda item: item[1], reverse=True)
    return {row["code"] for row, _score in ordered[:keep]}


def _window_return(
    prices: dict[str, float],
    day_str: str,
    window: int,
    *,
    dates: list[str] | None = None,
) -> float | None:
    dates = dates or sorted(prices)
    idx = bisect_right(dates, day_str) - 1
    if idx < window or idx < 0:
        return None
    current = prices.get(dates[idx])
    previous = prices.get(dates[idx - window])
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - 1.0


def _normalized_weights(weights: tuple[float, ...], count: int) -> tuple[float, ...]:
    selected = weights[:count]
    if len(selected) < count:
        selected = selected + tuple(1.0 for _ in range(count - len(selected)))
    total = sum(selected)
    if total <= 0:
        return tuple(1.0 / count for _ in range(count))
    return tuple(weight / total for weight in selected)


def _score_sort_key(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")
