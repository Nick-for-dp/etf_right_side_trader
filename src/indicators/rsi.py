"""RSI 指标: 相对强弱指数 RSI-14"""

import pandas as pd

from .base import BaseIndicator


class RSI(BaseIndicator):
    """
    RSI: 相对强弱指标
    默认以14天为周期计算平均收益(avg_gain)和平均损失(avg_loss)
    RS = avg_gain / avg_loss
    RSI = [100 - 100 / (1+RS)], RSI取值范围在[0, 100)
    """
    def __init__(self, period: int = 14):
        self.period = period
    
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        # 获取连续交易日的收盘价数据
        close = df['close']
        # 计算相邻两天的差价
        delta = close.diff()
        # 计算平均收益(avg_gain)与平均损失(avg_loss)
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(span=self.period, adjust=False).mean()
        avg_loss = loss.ewm(span=self.period, adjust=False).mean()

        rs = avg_gain / avg_loss
        rsi = 100.0 - 100 / (1 + rs)

        result = df[["date"]].copy()
        result["rsi"] = rsi
        return result
