"""Backtest-only experimental signal generators."""

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.backtest.ablation_config import ExperimentalSignalProfileConfig
from src.database import indicators_repo


def build_experimental_signal_frame(
    codes: list[str],
    start: date,
    end: date,
    profile: ExperimentalSignalProfileConfig,
    *,
    price_map: dict[str, dict[str, float]],
    code_volatility_groups: dict[str, str],
    fallback_signal_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build an in-memory signal frame for an experimental profile."""
    target_codes = [
        code for code in codes
        if code_volatility_groups.get(code, "unknown_vol") in profile.volatility_groups
    ]
    fallback_codes = [code for code in codes if code not in set(target_codes)]

    frames = []
    if target_codes:
        frames.append(_generate_profile_signals(target_codes, start, end, profile, price_map))
    if fallback_codes and not fallback_signal_df.empty:
        frames.append(fallback_signal_df[fallback_signal_df["code"].isin(fallback_codes)].copy())

    if not frames:
        return pd.DataFrame(columns=["code", "date", "signal", "signal_meta"])
    return pd.concat(frames, ignore_index=True).sort_values(["code", "date"]).reset_index(drop=True)


def _generate_profile_signals(
    codes: list[str],
    start: date,
    end: date,
    profile: ExperimentalSignalProfileConfig,
    price_map: dict[str, dict[str, float]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for code in codes:
        indicators = indicators_repo.find_by_code_between(code, start, end)
        for ind in indicators:
            day_str = str(ind.date)
            row = {"code": code, "date": day_str}
            row.update(ind.data)
            row["close"] = price_map.get(code, {}).get(day_str)
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["code", "date", "signal", "signal_meta"])

    df = pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)
    required = [
        "ma20", "ma60", "close", "dif", "dea", "rsi",
        "bb_upper", "bb_lower", "bb_mid", "bb_width",
        "adx14", "vol_ratio", "atr_pct",
    ]
    missing = [col for col in required if col not in df.columns]
    for col in missing:
        df[col] = np.nan

    outputs = []
    for code in df["code"].unique():
        code_df = df[df["code"] == code].sort_values("date").reset_index(drop=True)
        if profile.kind == "high_vol_balanced":
            outputs.extend(_generate_high_vol_balanced(code_df, profile))
        elif profile.kind == "low_vol_stable":
            outputs.extend(_generate_low_vol_stable(code_df, profile))
        else:
            raise ValueError(f"未知实验信号 profile: {profile.kind}")

    return pd.DataFrame(outputs, columns=["code", "date", "signal", "signal_meta"])


def _generate_high_vol_balanced(
    df: pd.DataFrame,
    profile: ExperimentalSignalProfileConfig,
) -> list[dict[str, Any]]:
    valid, invalid = _split_valid_rows(df)
    results = [_hold_row(row, profile) for _, row in invalid.iterrows()]
    if valid.empty:
        return results

    s_trend = _trend_signal(valid)
    s_macd = _macd_signal(valid)
    s_rsi = _high_vol_rsi_signal(valid["rsi"])
    s_bb = _high_vol_bb_signal(valid)
    s_volume = _volume_signal(valid["vol_ratio"])
    s_atr = _high_vol_atr_signal(valid["atr_pct"])
    score = (
        s_trend * 0.30
        + s_macd * 0.25
        + s_rsi * 0.15
        + s_bb * 0.15
        + s_volume * 0.10
        + s_atr * 0.05
    ) * 100

    trend_gate = (valid["ma20"] >= valid["ma60"]) | (valid["close"] >= valid["ma60"])
    macd_not_bad = _macd_hist(valid) >= -0.002
    positive_count = (
        (s_trend > 0).astype(int)
        + (s_macd > 0).astype(int)
        + (s_rsi > 0).astype(int)
        + (s_bb > 0).astype(int)
        + (s_volume > 0).astype(int)
    )
    sell_break = (
        (valid["close"] < valid["ma20"])
        & (_macd_hist(valid) < 0)
        & (valid["rsi"] < 45)
    ) | ((valid["close"] < valid["ma60"]) & (_macd_hist(valid) < 0))

    signal = pd.Series("HOLD", index=valid.index)
    signal[(score >= 45) & trend_gate & macd_not_bad & (valid["adx14"] >= 18) & (positive_count >= 3)] = "BUY"
    signal[(score <= -35) | sell_break] = "SELL"

    for idx, row in valid.iterrows():
        results.append(_signal_row(
            row=row,
            signal=signal.loc[idx],
            profile=profile,
            score=score.loc[idx],
            components={
                "s_trend": s_trend.loc[idx],
                "s_macd": s_macd.loc[idx],
                "s_rsi": s_rsi.loc[idx],
                "s_bb": s_bb.loc[idx],
                "s_volume": s_volume.loc[idx],
                "s_atr": s_atr.loc[idx],
            },
        ))
    return results


def _generate_low_vol_stable(
    df: pd.DataFrame,
    profile: ExperimentalSignalProfileConfig,
) -> list[dict[str, Any]]:
    valid, invalid = _split_valid_rows(df)
    results = [_hold_row(row, profile) for _, row in invalid.iterrows()]
    if valid.empty:
        return results

    s_trend = _low_vol_trend_signal(valid)
    s_pullback = _low_vol_pullback_signal(valid)
    s_rsi = _low_vol_rsi_repair_signal(valid["rsi"])
    s_macd = _low_vol_macd_signal(valid)
    s_volume = _low_vol_volume_signal(valid["vol_ratio"])
    score = (
        s_trend * 0.30
        + s_pullback * 0.25
        + s_rsi * 0.25
        + s_macd * 0.15
        + s_volume * 0.05
    ) * 100

    close_above_ma60 = valid["close"] >= valid["ma60"]
    repair_confirm = (s_pullback > 0) | (s_rsi > 0)
    macd_not_bad = _macd_hist(valid) >= -0.0015
    below_ma60_2 = (valid["close"] < valid["ma60"]).rolling(2, min_periods=1).sum() >= 2
    structure_break = below_ma60_2 & (_macd_hist(valid) < 0) & ((valid["rsi"] < 45) | (score < -20))

    signal = pd.Series("HOLD", index=valid.index)
    signal[(score >= 35) & close_above_ma60 & repair_confirm & macd_not_bad] = "BUY"
    signal[(score <= -30) | structure_break] = "SELL"

    for idx, row in valid.iterrows():
        results.append(_signal_row(
            row=row,
            signal=signal.loc[idx],
            profile=profile,
            score=score.loc[idx],
            components={
                "s_trend": s_trend.loc[idx],
                "s_pullback": s_pullback.loc[idx],
                "s_rsi": s_rsi.loc[idx],
                "s_macd": s_macd.loc[idx],
                "s_volume": s_volume.loc[idx],
            },
        ))
    return results


def _split_valid_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = [
        "ma20", "ma60", "close", "dif", "dea", "rsi",
        "bb_upper", "bb_lower", "bb_mid", "bb_width",
        "adx14", "vol_ratio", "atr_pct",
    ]
    mask = df[required].isna().any(axis=1)
    return df.loc[~mask].copy(), df.loc[mask].copy()


def _trend_signal(df: pd.DataFrame) -> pd.Series:
    spread = (df["ma20"] - df["ma60"]) / df["ma60"]
    position = (df["close"] - df["ma20"]) / df["ma20"]
    return (spread * 15 + position * 10).clip(-1, 1)


def _low_vol_trend_signal(df: pd.DataFrame) -> pd.Series:
    ma60_position = (df["close"] - df["ma60"]) / df["ma60"]
    spread = (df["ma20"] - df["ma60"]) / df["ma60"]
    return (ma60_position * 8 + spread * 12).clip(-1, 1)


def _macd_signal(df: pd.DataFrame) -> pd.Series:
    dif_norm = df["dif"] / df["close"]
    hist_norm = (df["dif"] - df["dea"]) / df["close"]
    return (dif_norm * 60 + hist_norm * 30).clip(-1, 1)


def _low_vol_macd_signal(df: pd.DataFrame) -> pd.Series:
    dif_norm = df["dif"] / df["close"]
    hist_norm = (df["dif"] - df["dea"]) / df["close"]
    return (dif_norm * 35 + hist_norm * 20).clip(-1, 1)


def _macd_hist(df: pd.DataFrame) -> pd.Series:
    return (df["dif"] - df["dea"]) / df["close"]


def _high_vol_rsi_signal(rsi: pd.Series) -> pd.Series:
    delta = rsi.diff().fillna(0.0)
    neutral_rise = ((rsi - 45) / 20).clip(0, 1) * (delta >= 0).astype(float)
    overheat = ((rsi - 72) / 13).clip(0, 1)
    weak = ((42 - rsi) / 12).clip(0, 1)
    return (neutral_rise - overheat - weak).clip(-1, 1)


def _low_vol_rsi_repair_signal(rsi: pd.Series) -> pd.Series:
    delta = rsi.diff().fillna(0.0)
    repair_zone = (1 - ((rsi - 52).abs() / 14)).clip(0, 1)
    rising = (delta >= 0).astype(float)
    overheat = ((rsi - 68) / 12).clip(0, 1)
    weak = ((38 - rsi) / 10).clip(0, 1)
    return (repair_zone * rising - overheat - weak).clip(-1, 1)


def _high_vol_bb_signal(df: pd.DataFrame) -> pd.Series:
    pos = _bb_position(df)
    base = ((pos - 0.45) / 0.4).clip(-1, 1)
    overextended = ((pos - 0.95) / 0.08).clip(0, 1)
    return (base - overextended).clip(-1, 1)


def _low_vol_pullback_signal(df: pd.DataFrame) -> pd.Series:
    pos = _bb_position(df)
    band_repair = (1 - ((pos - 0.45).abs() / 0.25)).clip(0, 1)
    close_near_ma20 = (1 - ((df["close"] - df["ma20"]).abs() / df["ma20"] / 0.04)).clip(0, 1)
    overextended = ((pos - 0.75) / 0.2).clip(0, 1)
    return ((band_repair + close_near_ma20) / 2 - overextended).clip(-1, 1)


def _bb_position(df: pd.DataFrame) -> pd.Series:
    width = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    return ((df["close"] - df["bb_lower"]) / width).fillna(0.5).clip(0, 1.2)


def _volume_signal(vol_ratio: pd.Series) -> pd.Series:
    return ((vol_ratio - 1.0) / 0.5).clip(-1, 1)


def _low_vol_volume_signal(vol_ratio: pd.Series) -> pd.Series:
    return ((vol_ratio - 0.75) / 0.5).clip(-1, 0.5)


def _high_vol_atr_signal(atr_pct: pd.Series) -> pd.Series:
    normal = (1 - ((atr_pct - 0.03).abs() / 0.03)).clip(0, 1)
    extreme = ((atr_pct - 0.06) / 0.03).clip(0, 1)
    return (normal - extreme).clip(-1, 1)


def _signal_row(
    *,
    row: pd.Series,
    signal: str,
    profile: ExperimentalSignalProfileConfig,
    score: float,
    components: dict[str, float],
) -> dict[str, Any]:
    meta = {
        "profile": profile.name,
        "score": round(float(score), 4),
        "adx": round(float(row["adx14"]), 4),
        "atr_pct": round(float(row["atr_pct"]), 6),
    }
    meta.update({key: round(float(value), 6) for key, value in components.items()})
    return {
        "code": row["code"],
        "date": row["date"],
        "signal": signal,
        "signal_meta": meta,
    }


def _hold_row(row: pd.Series, profile: ExperimentalSignalProfileConfig) -> dict[str, Any]:
    return {
        "code": row["code"],
        "date": row["date"],
        "signal": "HOLD",
        "signal_meta": {"profile": profile.name},
    }
