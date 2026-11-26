"""多指标评分策略（v2.5 limited，唯一生产策略）。

默认 profile：趋势/MACD/RSI/布林四因子加权评分（低波 ETF）。
high_vol profile：六因子评分 + 趋势闸门 + ADX 过滤（高波 ETF），
由 settings.yaml 的 strategy.params.volatility_signal_profiles.high_vol 开关。
每行信号只依赖当日指标和前一日 RSI，按 ETF 分别计算。
"""

import numpy as np
import pandas as pd

from .base import BaseStrategy

HIGH_VOL_PROFILE = "high_vol_balanced"
_HIGH_VOL_DEFAULTS = {
    "buy_threshold": 45,
    "sell_threshold": -35,
    "adx_min": 18,
    "min_positive": 3,
}


class MultiIndicatorScoring(BaseStrategy):
    """Score trend, momentum, RSI and Bollinger signals into BUY/SELL/HOLD."""

    def __init__(
        self,
        weights: dict,
        thresholds: dict,
        volatility_signal_profiles: dict | None = None,
        code_volatility_groups: dict[str, str] | None = None,
    ):
        self.weights = weights
        self.thresholds = thresholds
        self.volatility_signal_profiles = volatility_signal_profiles or {}
        self.code_volatility_groups = code_volatility_groups or {}
        self.version = self._resolve_version()

    @staticmethod
    def _calc_s_trend(spread: pd.Series, position: pd.Series) -> pd.Series:
        raw = spread * 15 + position * 10
        return raw.clip(-1, 1)

    @staticmethod
    def _calc_s_macd(dif_norm: pd.Series, macd_hist_norm: pd.Series) -> pd.Series:
        raw = dif_norm * 60 + macd_hist_norm * 30
        return raw.clip(-1, 1)

    @staticmethod
    def _calc_s_rsi(rsi: pd.Series) -> pd.Series:
        dev = (rsi - 50) / 20
        decay = 1.0 / (1.0 + np.exp((dev.abs() * 20 - 20) / 10))
        return (dev.clip(-1, 1) * decay).clip(-1, 1)

    @staticmethod
    def _calc_s_bb(pos_in_band: pd.Series, bb_width_pct: pd.Series) -> pd.Series:
        base = ((pos_in_band - 0.5) * 2).clip(-1, 1)
        width_factor = (bb_width_pct / 0.05).clip(0.3, 1.0)
        return (base * width_factor).clip(-1, 1)

    @staticmethod
    def _macd_hist(df: pd.DataFrame) -> pd.Series:
        return (df["dif"] - df["dea"]) / df["close"]

    @staticmethod
    def _bb_position(df: pd.DataFrame) -> pd.Series:
        width = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
        return ((df["close"] - df["bb_lower"]) / width).fillna(0.5).clip(0, 1.2)

    @staticmethod
    def _high_vol_rsi_signal(rsi: pd.Series) -> pd.Series:
        delta = rsi.diff().fillna(0.0)
        neutral_rise = ((rsi - 45) / 20).clip(0, 1) * (delta >= 0).astype(float)
        overheat = ((rsi - 72) / 13).clip(0, 1)
        weak = ((42 - rsi) / 12).clip(0, 1)
        return (neutral_rise - overheat - weak).clip(-1, 1)

    @classmethod
    def _high_vol_bb_signal(cls, df: pd.DataFrame) -> pd.Series:
        pos = cls._bb_position(df)
        base = ((pos - 0.45) / 0.4).clip(-1, 1)
        overextended = ((pos - 0.95) / 0.08).clip(0, 1)
        return (base - overextended).clip(-1, 1)

    @staticmethod
    def _volume_signal(vol_ratio: pd.Series) -> pd.Series:
        return ((vol_ratio - 1.0) / 0.5).clip(-1, 1)

    @staticmethod
    def _high_vol_atr_signal(atr_pct: pd.Series) -> pd.Series:
        normal = (1 - ((atr_pct - 0.03).abs() / 0.03)).clip(0, 1)
        extreme = ((atr_pct - 0.06) / 0.03).clip(0, 1)
        return (normal - extreme).clip(-1, 1)

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate BUY/SELL/HOLD signals from indicator rows."""
        df = df.sort_values(["code", "date"]).reset_index(drop=True)
        results = []

        for code in df["code"].unique():
            code_df = df[df["code"] == code].sort_values("date").reset_index(drop=True)
            if self._high_vol_enabled_for(code):
                results.extend(self._generate_high_vol_balanced(code_df))
            else:
                results.extend(self._generate_default(code_df))

        if results:
            return pd.DataFrame(results, columns=[
                "code", "date", "signal", "strategy_version", "signal_meta",
            ])
        return pd.DataFrame(
            columns=["code", "date", "signal", "strategy_version", "signal_meta"]
        )

    def _generate_default(self, code_df: pd.DataFrame) -> list[dict]:
        required = [
            "ma20", "ma60", "close", "dif", "dea", "rsi",
            "bb_upper", "bb_lower", "bb_mid", "bb_width",
            "adx14", "vol_ratio",
        ]
        valid, invalid = self._split_valid_rows(code_df, required)
        results = [self._signal_row(row, "HOLD", {}) for _, row in invalid.iterrows()]
        if valid.empty:
            return results

        spread = (valid["ma20"] - valid["ma60"]) / valid["ma60"]
        position = (valid["close"] - valid["ma20"]) / valid["ma20"]
        dif_norm = valid["dif"] / valid["close"]
        macd_hist_norm = self._macd_hist(valid)
        pos_in_band = (
            (valid["close"] - valid["bb_lower"])
            / (valid["bb_upper"] - valid["bb_lower"])
        )

        s_trend = self._calc_s_trend(spread, position)
        s_macd = self._calc_s_macd(dif_norm, macd_hist_norm)
        s_rsi = self._calc_s_rsi(valid["rsi"])
        bb_width_pct = valid["bb_width"]
        s_bb = self._calc_s_bb(pos_in_band, bb_width_pct)

        raw_score = (
            s_trend * self.weights["trend"]
            + s_macd * self.weights["macd"]
            + s_rsi * self.weights["rsi"]
            + s_bb * self.weights["bb"]
        )
        vol_mult = valid["vol_ratio"].clip(lower=0.6, upper=1.15) ** 0.3
        adx = valid["adx14"]
        adx_mult = np.where(adx < 20, 0.5, np.where(adx > 25, 1.0, 0.75))
        score = raw_score * vol_mult * adx_mult * 100

        signal = pd.Series("HOLD", index=valid.index)
        pos_count = (
            (s_trend > 0).astype(int)
            + (s_macd > 0).astype(int)
            + (s_rsi > 0).astype(int)
            + (s_bb > 0).astype(int)
        )
        signal[
            (score >= self.thresholds["buy"]) & (pos_count >= 2)
        ] = "BUY"

        neg_count = (
            (s_trend < 0).astype(int)
            + (s_macd < 0).astype(int)
            + (s_rsi < 0).astype(int)
            + (s_bb < 0).astype(int)
        )
        signal[(score <= self.thresholds["sell"]) & (neg_count >= 2)] = "SELL"

        adx_mult_series = pd.Series(adx_mult, index=valid.index)
        for idx, row in valid.iterrows():
            meta = {
                "s_trend": round(float(s_trend.loc[idx]), 6),
                "s_macd": round(float(s_macd.loc[idx]), 6),
                "s_rsi": round(float(s_rsi.loc[idx]), 6),
                "s_bb": round(float(s_bb.loc[idx]), 6),
                "bb_width_pct": round(float(bb_width_pct.loc[idx]), 6),
                "vol_mult": round(float(vol_mult.loc[idx]), 4),
                "adx_mult": round(float(adx_mult_series.loc[idx]), 4),
                "adx": round(float(adx.loc[idx]), 4),
                "raw_score": round(float(raw_score.loc[idx]), 6),
                "score": round(float(score.loc[idx]), 4),
            }
            results.append(self._signal_row(row, signal.loc[idx], meta))
        return results

    def _generate_high_vol_balanced(self, code_df: pd.DataFrame) -> list[dict]:
        required = [
            "ma20", "ma60", "close", "dif", "dea", "rsi",
            "bb_upper", "bb_lower", "bb_mid", "bb_width",
            "adx14", "vol_ratio", "atr_pct",
        ]
        valid, invalid = self._split_valid_rows(code_df, required)
        results = [
            self._signal_row(row, "HOLD", {"profile": HIGH_VOL_PROFILE})
            for _, row in invalid.iterrows()
        ]
        if valid.empty:
            return results

        spread = (valid["ma20"] - valid["ma60"]) / valid["ma60"]
        position = (valid["close"] - valid["ma20"]) / valid["ma20"]
        dif_norm = valid["dif"] / valid["close"]
        macd_hist_norm = self._macd_hist(valid)

        s_trend = self._calc_s_trend(spread, position)
        s_macd = self._calc_s_macd(dif_norm, macd_hist_norm)
        s_rsi = self._high_vol_rsi_signal(valid["rsi"])
        s_bb = self._high_vol_bb_signal(valid)
        s_volume = self._volume_signal(valid["vol_ratio"])
        s_atr = self._high_vol_atr_signal(valid["atr_pct"])
        score = (
            s_trend * 0.30
            + s_macd * 0.25
            + s_rsi * 0.15
            + s_bb * 0.15
            + s_volume * 0.10
            + s_atr * 0.05
        ) * 100

        buy_th = _HIGH_VOL_DEFAULTS["buy_threshold"]
        sell_th = _HIGH_VOL_DEFAULTS["sell_threshold"]
        adx_min = _HIGH_VOL_DEFAULTS["adx_min"]
        min_pos = _HIGH_VOL_DEFAULTS["min_positive"]

        trend_gate = (valid["ma20"] >= valid["ma60"]) | (valid["close"] >= valid["ma60"])
        macd_not_bad = self._macd_hist(valid) >= -0.002
        positive_count = (
            (s_trend > 0).astype(int)
            + (s_macd > 0).astype(int)
            + (s_rsi > 0).astype(int)
            + (s_bb > 0).astype(int)
            + (s_volume > 0).astype(int)
        )
        sell_break = (
            (valid["close"] < valid["ma20"])
            & (self._macd_hist(valid) < 0)
            & (valid["rsi"] < 45)
        ) | ((valid["close"] < valid["ma60"]) & (self._macd_hist(valid) < 0))

        signal = pd.Series("HOLD", index=valid.index)
        buy_mask = (
            (score >= buy_th)
            & trend_gate
            & macd_not_bad
            & (valid["adx14"] >= adx_min)
            & (positive_count >= min_pos)
        )
        signal[buy_mask] = "BUY"
        signal[(score <= sell_th) | sell_break] = "SELL"

        for idx, row in valid.iterrows():
            meta = {
                "profile": HIGH_VOL_PROFILE,
                "s_trend": round(float(s_trend.loc[idx]), 6),
                "s_macd": round(float(s_macd.loc[idx]), 6),
                "s_rsi": round(float(s_rsi.loc[idx]), 6),
                "s_bb": round(float(s_bb.loc[idx]), 6),
                "s_volume": round(float(s_volume.loc[idx]), 6),
                "s_atr": round(float(s_atr.loc[idx]), 6),
                "adx": round(float(valid.at[idx, "adx14"]), 4),
                "atr_pct": round(float(valid.at[idx, "atr_pct"]), 6),
                "score": round(float(score.loc[idx]), 4),
            }
            results.append(self._signal_row(row, signal.loc[idx], meta))
        return results

    def _high_vol_enabled_for(self, code: str) -> bool:
        group = self.code_volatility_groups.get(code, "unknown_vol")
        profile = self.volatility_signal_profiles.get(group) or {}
        return bool(profile.get("enabled", False))

    def _resolve_version(self) -> str:
        """信号版本：未开 high_vol profile 为 2.3；开启且参数为基线为 2.5。"""
        enabled = [
            profile.get("params", {}) or {}
            for profile in self.volatility_signal_profiles.values()
            if profile.get("enabled", False)
        ]
        if not enabled:
            return "2.3"
        for params in enabled:
            if any(params.get(key, value) != value for key, value in _HIGH_VOL_DEFAULTS.items()):
                return "custom"
        return "2.5"

    @staticmethod
    def _split_valid_rows(
        df: pd.DataFrame,
        required: list[str],
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        work = df.copy()
        for col in required:
            if col not in work.columns:
                work[col] = np.nan
        mask = work[required].isna().any(axis=1)
        return work.loc[~mask].copy(), work.loc[mask].copy()

    def _signal_row(self, row: pd.Series, signal: str, meta: dict) -> dict:
        return {
            "code": row["code"],
            "date": row["date"],
            "signal": signal,
            "strategy_version": self.version,
            "signal_meta": meta,
        }
