"""signals 表 ORM 映射。

Table: signals — 策略信号输出
Row example: code="588000", date=2026-04-25, signal="BUY", signal_meta={"trend": "up"}
"""

from datetime import date
from typing import Any

from sqlalchemy import Column, Date, PrimaryKeyConstraint, VARCHAR
from sqlalchemy.dialects.postgresql import JSONB

from src.database.schema.base import Base
from src.models.signal import Signal


class SignalOrm(Base):
    """signals 表 ORM 模型。"""
    __tablename__ = "signals"

    code = Column[str](VARCHAR(20), nullable=False)
    date = Column[date](Date, nullable=False)
    signal = Column[str](VARCHAR(10), nullable=False)
    strategy_version = Column[str](VARCHAR(10))
    signal_meta = Column[Any](JSONB, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("code", "date"),
    )

    def to_model(self) -> Signal:
        """转换为业务模型。"""
        return Signal(
            code=self.code,
            date=self.date,
            signal=self.signal,
            strategy_version=self.strategy_version or "",
            signal_meta=self.signal_meta or {},
        )
