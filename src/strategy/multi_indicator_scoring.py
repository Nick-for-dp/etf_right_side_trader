"""多指标综合评分策略（V2.0）。

四个子信号加权求和 → -100~+100 连续评分，Volume 作为置信度乘数。
评分后内部做阈值映射为 BUY/SELL/HOLD，下游 advisor 无需改动。
"""

import numpy as np
import pandas as pd

from .base import BaseStrategy


class MultiIndicatorScoring(BaseStrategy):
    """综合趋势、动能、RSI、布林带四维度加权评分。

    不做离散状态机——连续函数直接算分，避免信息损失。
    """

    def __init__(self, weights: dict, thresholds: dict):
        self.weights = weights
        self.thresholds = thresholds
        self.version = "2.0"

    # ── 子信号计算 ──

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
    def _calc_s_bb(pos_in_band: pd.Series) -> pd.Series:
        return ((pos_in_band - 0.5) * 2).clip(-1, 1)

    # ── 主入口 ──

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """综合趋势/动能/RSI/布林带四维度加权评分，生成 -100~+100 连续评分并映射为交易信号。

        不做离散状态机——四子信号连续加权求和，Volume 作为置信度乘数。
        评分后内部阈值映射为 BUY/SELL/HOLD，下游 advisor 无需改动。

        Args:
            df: 含 ma20、ma60、close、dif、dea、rsi、bb_upper、bb_lower、vol_ratio
                列的指标 DataFrame

        Returns:
            DataFrame，columns = [code, date, signal, strategy_version, signal_meta]，
            signal 可选值为 BUY / SELL / HOLD，
            signal_meta 包含 s_trend / s_macd / s_rsi / s_bb / vol_mult / raw_score / score

        Example:
            >>> strategy = MultiIndicatorScoring(
            ...     weights={"trend": 0.45, "macd": 0.30, "rsi": 0.15, "bb": 0.10},
            ...     thresholds={"buy": 30, "sell": -30},
            ... )
            >>> signals = strategy.generate(indicator_df)
            >>> signals[signals["signal"] != "HOLD"].head()
        """
        df = df.sort_values(["code", "date"]).reset_index(drop=True)

        required = ["ma20", "ma60", "close", "dif", "dea", "rsi",
                    "bb_upper", "bb_lower", "vol_ratio"]
        nan_mask = df[required].isna().any(axis=1)
        valid_df = df.loc[nan_mask == False].copy()
        nan_df = df[nan_mask]

        results = []

        if len(valid_df) > 0:
            for code in valid_df["code"].unique():
                mask = valid_df["code"] == code
                code_df = valid_df[mask].sort_values("date").reset_index(drop=True)

                # ── 第一步：从原始指标列派生中间变量 ──
                spread = (code_df["ma20"] - code_df["ma60"]) / code_df["ma60"]
                position = (code_df["close"] - code_df["ma20"]) / code_df["ma20"]
                dif_norm = code_df["dif"] / code_df["close"]
                macd_hist_norm = (code_df["dif"] - code_df["dea"]) / code_df["close"]
                pos_in_band = (
                    (code_df["close"] - code_df["bb_lower"])
                    / (code_df["bb_upper"] - code_df["bb_lower"])
                )

                # ── 第二步：计算四个子信号（每个映射到 [-1, 1]）──
                s_trend = self._calc_s_trend(spread, position)
                s_macd = self._calc_s_macd(dif_norm, macd_hist_norm)
                s_rsi = self._calc_s_rsi(code_df["rsi"])
                s_bb = self._calc_s_bb(pos_in_band)

                # ── 第三步：加权求和得到原始评分 ──
                raw_score = (
                    s_trend * self.weights["trend"]
                    + s_macd * self.weights["macd"]
                    + s_rsi * self.weights["rsi"]
                    + s_bb * self.weights["bb"]
                )

                # ── 第四步：成交量乘数调整（只衰减不放大，右侧交易不追量）──
                vol_mult = code_df["vol_ratio"].clip(lower=0.85, upper=1.0) ** 0.3
                vol_mult = vol_mult.clip(0.85, 1.0)
                score = raw_score * vol_mult * 100

                # ── 第五步：评分阈值 + 子信号一致性双重条件映射为 BUY / SELL / HOLD ──
                # 右侧交易核心原则：单一指标不构成入场理由，至少两个维度同时确认
                signal = pd.Series("HOLD", index=code_df.index)

                # BUY 条件：评分达标 + 至少 2 个子信号为正（避免 S_trend 独木难支）
                score_pass_buy = score >= self.thresholds["buy"]
                pos_count = (s_trend > 0).astype(int) + (s_macd > 0).astype(int) \
                    + (s_rsi > 0).astype(int) + (s_bb > 0).astype(int)
                consensus_buy = pos_count >= 2
                signal[score_pass_buy & consensus_buy] = "BUY"

                # SELL 条件：评分达标 + 至少 2 个子信号为负（对称原则，避免恐慌性离场）
                score_pass_sell = score <= self.thresholds["sell"]
                neg_count = (s_trend < 0).astype(int) + (s_macd < 0).astype(int) \
                    + (s_rsi < 0).astype(int) + (s_bb < 0).astype(int)
                consensus_sell = neg_count >= 2
                signal[score_pass_sell & consensus_sell] = "SELL"

                # ── 第六步：组装输出（signal_meta 存子信号分解值，便于调试和回测）──
                for i in code_df.index:
                    meta = {
                        "s_trend": round(float(s_trend[i]), 6),
                        "s_macd": round(float(s_macd[i]), 6),
                        "s_rsi": round(float(s_rsi[i]), 6),
                        "s_bb": round(float(s_bb[i]), 6),
                        "vol_mult": round(float(vol_mult[i]), 4),
                        "raw_score": round(float(raw_score[i]), 6),
                        "score": round(float(score[i]), 4),
                    }
                    results.append({
                        "code": code_df.at[i, "code"],
                        "date": code_df.at[i, "date"],
                        "signal": signal[i],
                        "strategy_version": self.version,
                        "signal_meta": meta,
                    })

        # 指标缺失的行 → 无脑 HOLD，不做判断
        for _, row in nan_df.iterrows():
            results.append({
                "code": row["code"],
                "date": row["date"],
                "signal": "HOLD",
                "strategy_version": self.version,
                "signal_meta": {},
            })

        if results:
            return pd.DataFrame(results, columns=[
                "code", "date", "signal", "strategy_version", "signal_meta",
            ])
        return pd.DataFrame(
            columns=["code", "date", "signal", "strategy_version", "signal_meta"]
        )
