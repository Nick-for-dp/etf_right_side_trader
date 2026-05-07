"""operation_advice 表 ORM 映射。

Table: operation_advice — 每日操作建议
Row example: code="588000", date=2026-04-25, position_id=1, signal="HOLD", advice="继续持有"
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Column, Date, Integer, Numeric, PrimaryKeyConstraint, VARCHAR

from src.database.schema.base import Base
from src.models.operation_advice import OperationAdvice


class OperationAdviceOrm(Base):
    """operation_advice 表 ORM 模型。"""
    __tablename__ = "operation_advice"

    code = Column[str](VARCHAR(20), nullable=False)
    date = Column[date](Date, nullable=False)
    position_id = Column[int](Integer, nullable=True)
    cost = Column[Decimal](Numeric[Decimal](12, 4))
    pnl_pct = Column[Decimal](Numeric[Decimal](10, 6))
    signal = Column[str](VARCHAR(10), nullable=False)
    advice = Column[str](VARCHAR(20), nullable=False)
    signal_source = Column[str](VARCHAR(20))

    __table_args__ = (
        PrimaryKeyConstraint("code", "date"),
    )

    def to_model(self) -> OperationAdvice:
        """转换为业务模型。"""
        return OperationAdvice(
            code=self.code,
            date=self.date,
            position_id=self.position_id,
            cost=float(self.cost) if self.cost is not None else None,
            pnl_pct=float(self.pnl_pct) if self.pnl_pct is not None else None,
            signal=self.signal,
            advice=self.advice,
            signal_source=self.signal_source or "",
        )
