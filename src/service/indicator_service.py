"""指标计算编排：取行情 → 调计算器 → 合并 → 逐日入库。

build_indicator_service 是唯一的指标注册入口，init / 每日流程 / 重建共用。
"""

from datetime import date, timedelta

import pandas as pd

from src.database import indicators_repo, quote_repo
from src.indicators import ADX, ATR, MASystem, MACD, BaseIndicator, Bollinger, RSI, VolumeIndicator
from src.utils import get_logger

logger = get_logger(__name__)

# 向前多取的行情只用于预热。MACD/RSI/ADX 含无限记忆的指数平滑，
# 预热长度会轻微影响数值，固定为 1500 天以保证历史与每日增量口径一致。
_LOOKBACK_PADDING = 1500


class IndicatorService:
    """管理指标计算器，负责注册计算器并编排计算与入库流程。"""

    def __init__(self):
        """初始化空的指标计算器列表。"""
        self._calculators: list[BaseIndicator] = []

    def register(self, calculator: BaseIndicator) -> None:
        """注册一个指标计算器。"""
        self._calculators.append(calculator)

    def calculate_and_save(self, code: str,
                           calc_start: date,
                           calc_end: date) -> int:
        """计算指定日期区间的指标并入库，返回保存的记录数。

        自动向前扩展行情查询范围（_LOOKBACK_PADDING 天），保证 MA 等
        rolling 计算有足够历史数据，但只保存 calc_start ~ calc_end 的结果。
        """
        if not self._calculators:
            logger.warning("未注册任何指标计算器，跳过。")
            return 0

        fetch_start = calc_start - timedelta(days=_LOOKBACK_PADDING)
        quotes = quote_repo.find_by_code_in_range(code, fetch_start, calc_end)
        if not quotes:
            logger.warning(f"{code} 在 {fetch_start} ~ {calc_end} 无行情数据，跳过。")
            return 0

        price_df = pd.DataFrame(
            [{
                "date": str(q.date),
                "open": q.open,
                "high": q.high,
                "low": q.low,
                "close": q.close,
                "volume": q.volume,
            } for q in quotes]
        ).sort_values("date").reset_index(drop=True)

        # 逐个计算器计算，按 date 左连接合并
        result = price_df[["date"]].copy()
        for calc in self._calculators:
            ind_df = calc.calculate(price_df)
            result = result.merge(ind_df, on="date", how="left")

        result = result[
            (result["date"] >= str(calc_start)) &
            (result["date"] <= str(calc_end))
        ]

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


def build_indicator_service(config) -> IndicatorService:
    """按 settings.yaml 构建生产指标集合（7 个）。

    这是唯一的指标注册入口，init / 每日流程 / rebuild 共用。
    """
    service = IndicatorService()
    service.register(MASystem(
        ma_short=config.strategy_params.get("ma_short", 20),
        ma_long=config.strategy_params.get("ma_long", 60),
    ))
    service.register(MACD())
    service.register(Bollinger(window=20, num_std=2.0))
    service.register(RSI(period=14))
    service.register(VolumeIndicator(window=20))
    service.register(ADX(period=14))
    service.register(ATR(period=20))
    return service
