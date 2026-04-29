"""MA 均线系统：MA20 / MA60 计算。"""

import pandas as pd

from .base import BaseIndicator


class MASystem(BaseIndicator):
    """计算 MA20 / MA60 均线系统。"""

    def __init__(self, ma_short: int = 20, ma_long: int = 60):
        """初始化均线参数。

        Args:
            ma_short: 短期均线窗口，默认 20
            ma_long: 长期均线窗口，默认 60
        """
        self.ma_short = ma_short
        self.ma_long = ma_long

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算短期和长期移动平均线。

        df 需含 date/close 列，返回 DataFrame 含 date/ma20/ma60 列。
        ma20 前 19 行、ma60 前 59 行为 NaN（rolling 窗口不足）。

        Args:
            df: 包含 date 和 close 列的行情数据

        Returns:
            含 date/ma20/ma60 列的 DataFrame

        Example:
            >>> import pandas as pd
            >>> df = pd.DataFrame({"date": ["2026-04-01", "2026-04-02"],
            ...                    "close": [1.0, 1.05]})
            >>> ma = MASystem(ma_short=2, ma_long=2)
            >>> result = ma.calculate(df)
            >>> print(result.columns.tolist())
            ['date', 'ma20', 'ma60']
        """
        result = df[["date"]].copy()
        result["ma20"] = df["close"].rolling(window=self.ma_short).mean()
        result["ma60"] = df["close"].rolling(window=self.ma_long).mean()
        return result
