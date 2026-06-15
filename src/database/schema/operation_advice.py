"""operation_advice 表 ORM 映射。

Table: operation_advice — 每日操作建议
Row example: code="588000", date=2026-04-25, position_id=1, signal="HOLD", advice="继续持有"
"""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, Date, Integer, Numeric, PrimaryKeyConstraint, VARCHAR
from sqlalchemy.dialects.postgresql import JSONB

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
    target_position_ratio = Column[Decimal](Numeric[Decimal](6, 4))
    target_budget_ratio = Column[Decimal](Numeric[Decimal](6, 4))
    entry_add_step = Column[int](Integer)
    score = Column[Decimal](Numeric[Decimal](10, 4))
    market_state = Column[str](VARCHAR(20))
    stop_loss_profile = Column[str](VARCHAR(20))
    blocked_reason = Column[str](VARCHAR(80))
    advice_meta = Column[Any](JSONB, nullable=False, default=dict)

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
            target_position_ratio=(
                float(self.target_position_ratio)
                if self.target_position_ratio is not None else None
            ),
            target_budget_ratio=(
                float(self.target_budget_ratio)
                if self.target_budget_ratio is not None else None
            ),
            entry_add_step=self.entry_add_step,
            score=float(self.score) if self.score is not None else None,
            market_state=self.market_state,
            stop_loss_profile=self.stop_loss_profile,
            blocked_reason=self.blocked_reason,
            advice_meta=self.advice_meta or {},
        )
