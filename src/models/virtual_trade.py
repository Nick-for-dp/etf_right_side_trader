"""虚拟交易业务模型。"""

from datetime import date

from pydantic import BaseModel


class VirtualTrade(BaseModel):
    """虚拟回测重建的一笔交易：已平仓或持仓中。

    exit_date 为空 → 未平仓，pnl_pct 为浮动盈亏，latest_price 有值
    exit_date 有值 → 已平仓，pnl_pct 为已实现盈亏，exit_reason 有值
    """
    code: str
    entry_date: date
    entry_price: float
    exit_date: date | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    holding_days: int = 0
    exit_reason: str | None = None
    latest_price: float | None = None
