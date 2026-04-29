"""ETF 日线行情业务模型。

Example:
    Quote(code="588000", date=date(2026,4,25),
          open=1.234, high=1.250, low=1.220, close=1.245,
          volume=123456789, nav=1.240, premium_rate=0.004032)
"""

import math
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Quote(BaseModel):
    """日线 OHLCV + NAV 行情。

    nav:       实时参考净值（IOPV），用于计算溢价率
    premium_rate: 溢价率 = (close - nav) / nav，正值为溢价，负值为折价
    """
    code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    nav: float | None = None
    premium_rate: float | None = None

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.quote import QuoteOrm

        nav_val = self.nav
        if nav_val is not None and (isinstance(nav_val, float) and math.isnan(nav_val)):
            nav_val = None

        pr_val = self.premium_rate
        if pr_val is not None and (isinstance(pr_val, float) and math.isnan(pr_val)):
            pr_val = None

        return QuoteOrm(
            code=self.code,
            date=self.date,
            open=Decimal(str(self.open)),
            high=Decimal(str(self.high)),
            low=Decimal(str(self.low)),
            close=Decimal(str(self.close)),
            volume=Decimal(str(self.volume)),
            nav=Decimal(str(nav_val)) if nav_val is not None else None,
            premium_rate=Decimal(str(pr_val)) if pr_val is not None else None,
        )
