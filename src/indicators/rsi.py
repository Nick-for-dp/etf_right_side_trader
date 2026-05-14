"""RSI 指标：相对强弱指数 RSI-14。"""

import pandas as pd

from .base import BaseIndicator


class RSI(BaseIndicator):
    """相对强弱指数 RSI-14，Wilder 平滑（与 MACD 口径一致）。

    计算逻辑：RS = avg_gain / avg_loss → RSI = 100 - 100/(1+RS)
    取值范围 [0, 100)，前 period 行的 RSI 值因 avg_gain/avg_loss 在积累期而不稳定。
    """

    def __init__(self, period: int = 14):
        self.period = period

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        # 获取连续交易日的收盘价数据
        close = df["close"]
        # 计算相邻两天的差价，拆分为涨幅和跌幅
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        # Wilder 平滑计算平均收益与平均损失
        avg_gain = gain.ewm(span=self.period, adjust=False).mean()
        avg_loss = loss.ewm(span=self.period, adjust=False).mean()
        # 相对强弱 → RSI
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)

        result = df[["date"]].copy()
        result["rsi"] = rsi
        return result
