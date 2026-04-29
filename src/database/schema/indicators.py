"""indicators 表 ORM 映射。

Table: indicators — 技术指标快照（JSONB）
Row example: code="588000", date=2026-04-25, data={"ma20": 1.234, "ma60": 1.198}
"""

from datetime import date
from typing import Any

from sqlalchemy import Column, Date, PrimaryKeyConstraint, VARCHAR
from sqlalchemy.dialects.postgresql import JSONB

from src.database.schema.base import Base
from src.models.indicators import Indicators


class IndicatorsOrm(Base):
    """indicators 表 ORM 模型。"""
    __tablename__ = "indicators"

    code = Column[str](VARCHAR(20), nullable=False)
    date = Column[date](Date, nullable=False)
    data = Column[Any](JSONB, nullable=False, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("code", "date"),
    )

    def to_model(self) -> Indicators:
        """转换为业务模型。"""
        return Indicators(
            code=self.code,
            date=self.date,
            data=self.data or {},
        )
