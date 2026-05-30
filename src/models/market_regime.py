"""市场热度状态业务模型。"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class MarketRegime(BaseModel):
    """单日市场热度快照。"""

    date: date
    state: str
    score: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.market_regime import MarketRegimeOrm

        return MarketRegimeOrm(
            date=self.date,
            state=self.state,
            score=self.score,
            data=self.data,
        )
