"""布林带指标：中轨 MA20，上下轨 ±2σ，带宽。"""

import pandas as pd

from .base import BaseIndicator


class Bollinger(BaseIndicator):
    """布林带：MA20 中轨 + 2σ 通道 + 带宽比。

    bb_width = (upper - lower) / mid，值越小带宽越窄（挤压形态）。
    """

    def __init__(self, window: int = 20, num_std: float = 2.0):
        self.window = window
        self.num_std = num_std

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        mid = close.rolling(window=self.window).mean()
        std = close.rolling(window=self.window).std(ddof=1)
        upper = mid + self.num_std * std
        lower = mid - self.num_std * std
        width = (upper - lower) / mid

        result = df[["date"]].copy()
        result["bb_mid"] = mid
        result["bb_upper"] = upper
        result["bb_lower"] = lower
        result["bb_width"] = width
        return result
