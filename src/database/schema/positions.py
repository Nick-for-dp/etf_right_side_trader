"""positions 表 ORM 映射。

Table: positions — 用户持仓
Row example: id=1, code="588000", cost=1.2000, shares=10000, entry_date=2026-03-16,
             first_entry_date=2026-03-15, add_count=1
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Column, Date, Integer, Numeric, VARCHAR

from src.database.schema.base import Base
from src.models.position import Position


class PositionOrm(Base):
    """positions 表 ORM 模型。"""
    __tablename__ = "positions"

    id = Column[int](Integer, primary_key=True, autoincrement=True)
    code = Column[str](VARCHAR(20), nullable=False)
    cost = Column[Decimal](Numeric[Decimal](12, 4), nullable=False)
    shares = Column[int](Integer, nullable=False)
    entry_date = Column[date](Date, nullable=False)
    first_entry_date = Column[date](Date, nullable=False)
    add_count = Column[int](Integer, nullable=False, default=0)

    def to_model(self) -> Position:
        """转换为业务模型。"""
        return Position(
            id=self.id,
            code=self.code,
            cost=float(self.cost),
            shares=self.shares,
            entry_date=self.entry_date,
            first_entry_date=self.first_entry_date or self.entry_date,
            add_count=self.add_count or 0,
        )
