"""用户真实交易记录业务模型。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from src.models.enums import TradeAction


class TradeRecord(BaseModel):
    """单笔真实交易流水。

    action: BUY / ADD / REDUCE / SELL
    """

    id: int | None = None
    code: str
    action: TradeAction
    trade_date: date
    price: float
    shares: int
    created_at: datetime | None = None

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.trade_record import TradeRecordOrm

        kwargs = {
            "id": self.id if self.id else None,
            "code": self.code,
            "action": self.action.value,
            "trade_date": self.trade_date,
            "price": Decimal(str(self.price)),
            "shares": self.shares,
        }
        if self.created_at is not None:
            kwargs["created_at"] = self.created_at
        return TradeRecordOrm(**kwargs)
