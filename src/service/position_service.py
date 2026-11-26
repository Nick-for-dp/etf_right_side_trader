"""持仓记账：建仓/加仓/减仓/清仓，与 trade_records 同事务写入。

口径：
    保本价 = 剩余持仓买入成本 / 剩余份额。减仓/清仓不改变保本价。
    entry_date       = 最近一次买入日期（加仓冷却用）
    first_entry_date = 本轮持仓首次建仓日期（持有期上限用）
    add_count        = 本轮持仓已完成的加仓次数（加仓阶梯用），清仓后归零
"""

from datetime import date
from decimal import Decimal

from src.database.connection import get_session
from src.database.schema import PositionOrm, TradeRecordOrm
from src.models import Position
from src.models.enums import TradeAction


class PositionService:
    """持仓记账业务逻辑。"""

    @staticmethod
    def execute_buy(
        code: str,
        price: float,
        shares: int,
        trade_date: date,
    ) -> tuple[Position, TradeAction]:
        """建仓或加仓：重算加权保本价，加仓次数 +1，并写入 BUY/ADD 流水。"""
        _validate_trade_inputs(price, shares)
        session = get_session()
        try:
            old = (
                session.query(PositionOrm)
                .filter(PositionOrm.code == code)
                .with_for_update()
                .first()
            )
            if old is None:
                action = TradeAction.BUY
                pos_orm = PositionOrm(
                    code=code,
                    cost=Decimal(str(round(price, 4))),
                    shares=shares,
                    entry_date=trade_date,
                    first_entry_date=trade_date,
                    add_count=0,
                )
                session.add(pos_orm)
            else:
                action = TradeAction.ADD
                total_cost = float(old.cost) * old.shares + price * shares
                total_shares = old.shares + shares
                old.cost = Decimal(str(round(total_cost / total_shares, 4)))
                old.shares = total_shares
                old.entry_date = trade_date
                old.add_count = (old.add_count or 0) + 1
                pos_orm = old

            session.add(TradeRecordOrm(
                code=code,
                action=action.value,
                trade_date=trade_date,
                price=Decimal(str(round(price, 4))),
                shares=shares,
            ))
            session.commit()
            return pos_orm.to_model(), action
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def execute_sell(
        code: str,
        price: float,
        shares: int,
        trade_date: date,
    ) -> tuple[Position | None, TradeAction]:
        """减仓或清仓：保本价不变，份额减少，并写入 REDUCE/SELL 流水。"""
        _validate_trade_inputs(price, shares)
        session = get_session()
        try:
            old = (
                session.query(PositionOrm)
                .filter(PositionOrm.code == code)
                .with_for_update()
                .first()
            )
            if old is None:
                raise ValueError(f"未找到 {code} 的持仓")

            if shares >= old.shares:
                action = TradeAction.SELL
                session.delete(old)
                result = None
            else:
                action = TradeAction.REDUCE
                old.shares = old.shares - shares
                result = old

            session.add(TradeRecordOrm(
                code=code,
                action=action.value,
                trade_date=trade_date,
                price=Decimal(str(round(price, 4))),
                shares=shares,
            ))
            session.commit()
            return (result.to_model() if result is not None else None), action
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _validate_trade_inputs(price: float, shares: int) -> None:
    if price <= 0:
        raise ValueError("交易价格必须大于 0")
    if shares <= 0:
        raise ValueError("交易份额必须大于 0")
