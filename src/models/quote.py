"""ETF 日线行情业务模型。

Example:
    Quote(code="588000", date=date(2026,4,25),
          open=1.234, high=1.250, low=1.220, close=1.245, volume=123456789)
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Quote(BaseModel):
    """日线 OHLCV 行情。"""

    code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.quote import QuoteOrm

        return QuoteOrm(
            code=self.code,
            date=self.date,
            open=Decimal(str(self.open)),
            high=Decimal(str(self.high)),
            low=Decimal(str(self.low)),
            close=Decimal(str(self.close)),
            volume=Decimal(str(self.volume)),
        )
