"""quote 表 ORM 映射。

Table: quote — ETF 日线 OHLCV + NAV
Row example: code="588000", date=2026-04-25, close=1.245, nav=1.240
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Column, Date, Numeric, VARCHAR, PrimaryKeyConstraint

from src.database.schema.base import Base
from src.models.quote import Quote


class QuoteOrm(Base):
    """quote 表 ORM 模型。"""
    __tablename__ = "quote"

    code = Column[str](VARCHAR(20), nullable=False)
    date = Column[date](Date, nullable=False)
    open = Column[Decimal](Numeric[Decimal](12, 4))
    high = Column[Decimal](Numeric[Decimal](12, 4))
    low = Column[Decimal](Numeric[Decimal](12, 4))
    close = Column[Decimal](Numeric[Decimal](12, 4))
    volume = Column[Decimal](Numeric[Decimal](16, 2))
    nav = Column[Decimal](Numeric[Decimal](12, 4))
    premium_rate = Column[Decimal](Numeric[Decimal](10, 6))

    __table_args__ = (
        PrimaryKeyConstraint("code", "date"),
    )

    def to_model(self) -> Quote:
        """转换为业务模型。"""
        return Quote(
            code=self.code,
            date=self.date,
            open=float(self.open) if self.open is not None else 0.0,
            high=float(self.high) if self.high is not None else 0.0,
            low=float(self.low) if self.low is not None else 0.0,
            close=float(self.close) if self.close is not None else 0.0,
            volume=float(self.volume) if self.volume is not None else 0.0,
            nav=float(self.nav) if self.nav is not None else None,
            premium_rate=float(self.premium_rate) if self.premium_rate is not None else None,
        )
