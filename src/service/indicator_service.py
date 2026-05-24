"""指标计算编排：取行情 → 调计算器 → 合并 → 逐日入库。"""

from datetime import date, timedelta

import pandas as pd

from src.database import indicators_repo, quote_repo
from src.indicators import BaseIndicator
from src.utils import get_logger

logger = get_logger(__name__)

# 安全冗余窗口：拉取行情时往前多取的天数，保证 rolling 计算有足够历史
# v2.1A 升级：LongTermOdds 需要 L+H ≈ 1008 交易日 ≈ 4 年，改为 1500 日历天
_LOOKBACK_PADDING = 1500


class IndicatorService:
    """管理指标计算器，负责注册计算器并编排计算与入库流程。"""

    def __init__(self):
        """初始化空的指标计算器列表。"""
        self._calculators: list[BaseIndicator] = []

    def register(self, calculator: BaseIndicator) -> None:
        """注册一个指标计算器。v1.1 只需加一行 register(MACD())。"""
        self._calculators.append(calculator)

    def calculate_and_save(self, code: str,
                           calc_start: date,
                           calc_end: date) -> int:
        """计算指定日期区间的指标并入库，返回保存的记录数。

        自动向前扩展行情查询范围（_LOOKBACK_PADDING 天），保证 MA 等
        rolling 计算有足够历史数据，但只保存 calc_start ~ calc_end 的结果。

        Args:
            code: ETF 代码
            calc_start: 计算起始日期
            calc_end: 计算截止日期

        Returns:
            成功保存的指标记录条数

        Example:
            >>> service = IndicatorService()
            >>> service.register(MASystem(20, 60))
            >>> n = service.calculate_and_save("588000", date(2026, 4, 25), date(2026, 4, 25))
            >>> n > 0
            True
        """
        if not self._calculators:
            logger.warning("未注册任何指标计算器，跳过。")
            return 0

        # 拉取足够历史的行情数据
        fetch_start = calc_start - timedelta(days=_LOOKBACK_PADDING)
        quotes = quote_repo.find_by_code_in_range(code, fetch_start, calc_end)
        if not quotes:
            logger.warning(f"{code} 在 {fetch_start} ~ {calc_end} 无行情数据，跳过。")
            return 0

        # 转 DataFrame，按 date 升序
        # v2.1A：新增 nav 和 premium_rate，供 LongTermOdds 使用
        price_df = pd.DataFrame(
            [{
                "date": str(q.date),
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "close": q.close,
                "volume": q.volume,
                "nav": q.nav,
                "premium_rate": q.premium_rate,
            } for q in quotes]
        ).sort_values("date").reset_index(drop=True)

        # 逐个计算器计算，按 date 左连接合并
        result = price_df[["date"]].copy()
        for calc in self._calculators:
            ind_df = calc.calculate(price_df)
            result = result.merge(ind_df, on="date", how="left")

        # 只保留目标区间
        result = result[
            (result["date"] >= str(calc_start)) &
            (result["date"] <= str(calc_end))
        ]

        # 逐行保存
        saved = 0
        for _, row in result.iterrows():
            data = {
                k: v for k, v in row.items()
                if k != "date" and pd.notna(v)
            }
            if data:
                indicators_repo.save(code, row["date"], data)
                saved += 1

        return saved
