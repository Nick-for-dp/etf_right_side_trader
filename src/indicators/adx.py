"""ADX 指标：平均趋向指数 ADX(14)，衡量趋势强度而非方向。

ADX > 25 → 趋势行情，趋势跟随策略有效
ADX < 20 → 震荡行情，应降低信号置信度
"""

import pandas as pd
import numpy as np

from .base import BaseIndicator


class ADX(BaseIndicator):
    """平均趋向指数 ADX(14)。

    计算 True Range → +DI / -DI → DX → ADX(Wilder 平滑)。
    输出 adx14 / plus_di / minus_di 三列。
    """

    def __init__(self, period: int = 14):
        self.period = period

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # ── Step 1: True Range ──
        prev_close = close.shift(1)
        tr = pd.concat([
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        # ── Step 2: ±DM ──
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = pd.Series(0.0, index=df.index)
        minus_dm = pd.Series(0.0, index=df.index)

        up_gt_down = (up_move > down_move) & (up_move > 0)
        down_gt_up = (down_move > up_move) & (down_move > 0)
        plus_dm[up_gt_down] = up_move[up_gt_down]
        minus_dm[down_gt_up] = down_move[down_gt_up]

        # ── Step 3: Wilder 平滑 ──
        smoothed_tr = tr.ewm(span=self.period, adjust=False).mean()
        smoothed_plus_dm = plus_dm.ewm(span=self.period, adjust=False).mean()
        smoothed_minus_dm = minus_dm.ewm(span=self.period, adjust=False).mean()

        # ── Step 4: ±DI ──
        plus_di = 100.0 * smoothed_plus_dm / smoothed_tr.replace(0, np.nan)
        minus_di = 100.0 * smoothed_minus_dm / smoothed_tr.replace(0, np.nan)

        # ── Step 5: DX → ADX ──
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(span=self.period, adjust=False).mean()

        result = df[["date"]].copy()
        result["adx14"] = adx
        result["plus_di"] = plus_di
        result["minus_di"] = minus_di
        return result
