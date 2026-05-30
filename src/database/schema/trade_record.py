"""trade_records 表 ORM 映射。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, VARCHAR, func

from src.database.schema.base import Base
from src.models.trade_record import TradeRecord
from src.models.enums import TradeAction


class TradeRecordOrm(Base):
    """用户真实交易流水 ORM 模型。"""

    __tablename__ = "trade_records"

    id = Column[int](Integer, primary_key=True, autoincrement=True)
    code = Column[str](VARCHAR(20), nullable=False, index=True)
    action = Column[str](VARCHAR(10), nullable=False)
    trade_date = Column[date](Date, nullable=False, index=True)
    price = Column[Decimal](Numeric[Decimal](12, 4), nullable=False)
    shares = Column[int](Integer, nullable=False)
    created_at = Column[datetime](
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )

    def to_model(self) -> TradeRecord:
        """转换为业务模型。"""
        return TradeRecord(
            id=self.id,
            code=self.code,
            action=TradeAction(self.action),
            trade_date=self.trade_date,
            price=float(self.price),
            shares=self.shares,
            created_at=self.created_at,
        )
