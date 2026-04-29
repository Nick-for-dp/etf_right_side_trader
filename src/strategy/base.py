"""策略抽象基类。

策略负责从 indicators 数据中生成交易信号。
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """策略抽象，所有策略实现 generate 方法。"""

    @abstractmethod
    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """从指标 DataFrame 生成交易信号。

        Args:
            df: 来自 indicators 表展开后的 DataFrame，包含各行的 code、date 及指标字段

        Returns:
            DataFrame，columns = [code, date, signal, strategy_version, signal_meta]
        """
        ...
