"""market_index_quote 表 ORM 映射。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Column, Date, Numeric, PrimaryKeyConstraint, VARCHAR

from src.database.schema.base import Base
from src.models.market_index_quote import MarketIndexQuote


class MarketIndexQuoteOrm(Base):
    """市场指数日线行情 ORM 模型。"""

    __tablename__ = "market_index_quote"

    index_code = Column[str](VARCHAR(20), nullable=False)
    date = Column[date](Date, nullable=False)
    open = Column[Decimal](Numeric[Decimal](14, 4))
    high = Column[Decimal](Numeric[Decimal](14, 4))
    low = Column[Decimal](Numeric[Decimal](14, 4))
    close = Column[Decimal](Numeric[Decimal](14, 4))
    volume = Column[Decimal](Numeric[Decimal](20, 2))
    amount = Column[Decimal](Numeric[Decimal](20, 2))

    __table_args__ = (
        PrimaryKeyConstraint("index_code", "date"),
    )

    def to_model(self) -> MarketIndexQuote:
        """转换为业务模型。"""
        return MarketIndexQuote(
            index_code=self.index_code,
            date=self.date,
            open=float(self.open) if self.open is not None else 0.0,
            high=float(self.high) if self.high is not None else 0.0,
            low=float(self.low) if self.low is not None else 0.0,
            close=float(self.close) if self.close is not None else 0.0,
            volume=float(self.volume) if self.volume is not None else None,
            amount=float(self.amount) if self.amount is not None else None,
        )
