"""market_regime 表 ORM 映射。"""

from datetime import date
from typing import Any

from sqlalchemy import Column, Date, Numeric, PrimaryKeyConstraint, VARCHAR
from sqlalchemy.dialects.postgresql import JSONB

from src.database.schema.base import Base
from src.models.market_regime import MarketRegime


class MarketRegimeOrm(Base):
    """市场热度状态 ORM 模型。"""

    __tablename__ = "market_regime"

    date = Column[date](Date, nullable=False)
    state = Column[str](VARCHAR(20), nullable=False)
    score = Column[float](Numeric(10, 4))
    data = Column[Any](JSONB, nullable=False, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("date"),
    )

    def to_model(self) -> MarketRegime:
        """转换为业务模型。"""
        return MarketRegime(
            date=self.date,
            state=self.state,
            score=float(self.score) if self.score is not None else None,
            data=self.data or {},
        )
