"""MACD 指标：DIF / DEA / MACD 柱。"""

import pandas as pd

from .base import BaseIndicator


class MACD(BaseIndicator):
    """EMA12/EMA26 派生标准 MACD 指标。

    DIF  = EMA(fast) - EMA(slow)
    DEA  = EMA(signal) of DIF
    MACD = 2 × (DIF - DEA)

    使用 Wilder 平滑 (adjust=False)，与主流交易平台一致。
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """从 close 价格计算 MACD 三线。

        Args:
            df: 含 date / close 列的行情 DataFrame

        Returns:
            含 date / dif / dea / macd 列的 DataFrame，
            窗口不足的日期对应列为 NaN
        """
        close = df["close"]
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal, adjust=False).mean()

        result = df[["date"]].copy()
        result["dif"] = dif
        result["dea"] = dea
        result["macd"] = 2 * (dif - dea)
        return result
