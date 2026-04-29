"""数据抓取抽象基类。"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseFetcher(ABC):
    """数据源抽象，所有抓取器实现此接口。"""

    @abstractmethod
    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """拉取日线 OHLCV 数据。

        Args:
            symbol: ETF 代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            包含 date/open/high/low/close/volume/nav 列的 DataFrame
        """
        ...
