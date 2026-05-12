"""成交量指标：20 日均量 + 量比。"""

import pandas as pd

from .base import BaseIndicator


class VolumeIndicator(BaseIndicator):
    """成交量均线及量比。

    vol_ratio > 1 表示放量，< 1 表示缩量。
    """

    def __init__(self, window: int = 20):
        self.window = window

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        volume = df["volume"]
        vol_ma = volume.rolling(window=self.window).mean()
        vol_ratio = volume / vol_ma

        result = df[["date"]].copy()
        result["vol_ma20"] = vol_ma
        result["vol_ratio"] = vol_ratio
        return result
