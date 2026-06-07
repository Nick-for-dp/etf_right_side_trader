"""持仓业务模型。

Example:
    Position(id=1, code="588000", cost=1.2000, shares=10000, entry_date=date(2026,3,15))
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Position(BaseModel):
    """单笔持仓记录。

    cost:       当前剩余持仓保本价；建仓/加仓按加权均价，减仓按卖出回款摊薄
    shares:     持有份额
    entry_date: 建仓日期
    """
    id: int | None = None
    code: str
    cost: float
    shares: int
    entry_date: date

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.positions import PositionOrm
        return PositionOrm(
            id=self.id if self.id else None,
            code=self.code,
            cost=Decimal(str(self.cost)),
            shares=self.shares,
            entry_date=self.entry_date,
        )
