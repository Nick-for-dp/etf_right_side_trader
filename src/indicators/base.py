"""技术指标抽象基类。

每个指标模块实现 calculate(df) -> DataFrame，各计算器结果由
IndicatorService 按 date 合并后写入 indicators 表。
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseIndicator(ABC):
    """指标计算抽象基类，所有指标计算器需实现 calculate 方法。"""

    @abstractmethod
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """根据输入的 OHLCV 数据计算技术指标。

        输入 DataFrame 需包含 date/close 列（按 date 升序排列），
        返回含 date + 指标列的 DataFrame，未达计算窗口的日期对应列为 NaN。

        Args:
            df: 包含 date 和 close 列的行情数据

        Returns:
            含 date 及所有指标列的 DataFrame
        """
        ...
