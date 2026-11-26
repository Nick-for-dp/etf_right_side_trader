"""持仓业务模型。

Example:
    Position(id=1, code="588000", cost=1.2000, shares=10000,
             entry_date=date(2026,3,16), first_entry_date=date(2026,3,15), add_count=1)
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Position(BaseModel):
    """单个 ETF 的持仓。

    cost:             保本价 = 剩余持仓买入成本 / 剩余份额（减仓不改变保本价）
    shares:           持有份额
    entry_date:       最近一次买入（建仓或加仓）日期，用于加仓冷却
    first_entry_date: 首次建仓日期，用于持有期上限
    add_count:        当前持仓已完成加仓次数，清仓后归零
    """

    id: int | None = None
    code: str
    cost: float
    shares: int
    entry_date: date
    first_entry_date: date | None = None
    add_count: int = 0

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.positions import PositionOrm
        return PositionOrm(
            id=self.id if self.id else None,
            code=self.code,
            cost=Decimal(str(self.cost)),
            shares=self.shares,
            entry_date=self.entry_date,
            first_entry_date=self.first_entry_date or self.entry_date,
            add_count=self.add_count,
        )
