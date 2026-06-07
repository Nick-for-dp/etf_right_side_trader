"""ATR 指标：平均真实波幅 ATR(20)，衡量波动率。

atr_pct = atr20 / close，用于动态止损和评分阈值调整。
"""

import pandas as pd
import numpy as np

from .base import BaseIndicator


class ATR(BaseIndicator):
    """平均真实波幅 ATR(20)。

    True Range → Wilder 平滑 → ATR。
    输出 atr20 / atr_pct 两列。
    """

    def __init__(self, period: int = 20):
        self.period = period

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # True Range
        prev_close = close.shift(1)
        tr = pd.concat([
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        # Wilder 平滑：alpha = 1 / period。
        atr = tr.ewm(alpha=1 / self.period, adjust=False).mean()

        result = df[["date"]].copy()
        result["atr20"] = atr
        result["atr_pct"] = atr / close.replace(0, np.nan)
        return result
