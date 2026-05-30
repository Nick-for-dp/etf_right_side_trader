"""市场指数日线行情业务模型。"""

import math
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class MarketIndexQuote(BaseModel):
    """宽基指数日线 OHLCV + 成交额。"""

    index_code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.market_index_quote import MarketIndexQuoteOrm

        volume_val = _none_if_nan(self.volume)
        amount_val = _none_if_nan(self.amount)

        return MarketIndexQuoteOrm(
            index_code=self.index_code,
            date=self.date,
            open=Decimal(str(self.open)),
            high=Decimal(str(self.high)),
            low=Decimal(str(self.low)),
            close=Decimal(str(self.close)),
            volume=Decimal(str(volume_val)) if volume_val is not None else None,
            amount=Decimal(str(amount_val)) if amount_val is not None else None,
        )


def _none_if_nan(value: float | None) -> float | None:
    if value is not None and isinstance(value, float) and math.isnan(value):
        return None
    return value
