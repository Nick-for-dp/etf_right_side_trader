"""持仓管理业务逻辑：加仓均价重算、减仓保本价重算。"""

from datetime import date
from decimal import Decimal

from src.database.connection import get_session
from src.database import positions_repo
from src.database.schema import PositionOrm, TradeRecordOrm
from src.models import Position
from src.models.enums import TradeAction


class PositionService:
    """持仓管理业务逻辑。"""

    @staticmethod
    def get_holding_map() -> dict[str, date]:
        """返回当前持仓映射 {code: entry_date}。"""
        positions = positions_repo.find_all()
        return {p.code: p.entry_date for p in positions}

    @staticmethod
    def add(code: str, cost: float, shares: int, entry_date: date) -> Position:
        """建仓或加仓。已有持仓时重算加权平均成本。

        Args:
            code: ETF 代码
            cost: 本次买入价
            shares: 本次买入份额
            entry_date: 入场日期

        Returns:
            保存后的 Position 对象
        """
        old = positions_repo.find_by_code(code)
        if old is None:
            pos = Position(
                code=code, cost=cost, shares=shares, entry_date=entry_date
            )
        else:
            total_cost = old.cost * old.shares + cost * shares
            total_shares = old.shares + shares
            pos = Position(
                id=old.id,
                code=code,
                cost=round(total_cost / total_shares, 4),
                shares=total_shares,
                entry_date=entry_date,
            )
        return positions_repo.save(pos)

    @staticmethod
    def execute_buy(
        code: str,
        price: float,
        shares: int,
        trade_date: date,
    ) -> tuple[Position, TradeAction]:
        """Atomically update position and insert BUY/ADD trade record."""
        _validate_trade_inputs(price, shares)
        session = get_session()
        try:
            old = (
                session.query(PositionOrm)
                .filter(PositionOrm.code == code)
                .with_for_update()
                .first()
            )
            action = TradeAction.BUY
            if old is None:
                pos_orm = PositionOrm(
                    code=code,
                    cost=Decimal(str(round(price, 4))),
                    shares=shares,
                    entry_date=trade_date,
                )
                session.add(pos_orm)
                session.flush()
            else:
                action = TradeAction.ADD
                total_cost = float(old.cost) * old.shares + price * shares
                total_shares = old.shares + shares
                old.cost = Decimal(str(round(total_cost / total_shares, 4)))
                old.shares = total_shares
                old.entry_date = trade_date
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
    def reduce(code: str, sell_shares: int, sell_price: float) -> Position | None:
        """减仓。卖出份额 >= 持仓时清仓返回 None，否则更新份额和保本价。

        Args:
            code: ETF 代码
            sell_shares: 本次卖出份额
            sell_price: 本次卖出价

        Returns:
            更新后的 Position，清仓时返回 None
        """
        old = positions_repo.find_by_code(code)
        if old is None:
            raise ValueError(f"未找到 {code} 的持仓")
        if sell_shares <= 0:
            raise ValueError("卖出份额必须大于 0")
        if sell_price <= 0:
            raise ValueError("卖出价必须大于 0")
        if sell_shares >= old.shares:
            positions_repo.delete_by_id(old.id)
            return None

        remaining_shares = old.shares - sell_shares
        remaining_cost = old.cost * old.shares - sell_price * sell_shares
        pos = Position(
            id=old.id,
            code=code,
            cost=round(remaining_cost / remaining_shares, 4),
            shares=remaining_shares,
            entry_date=old.entry_date,
        )
        return positions_repo.save(pos)

    @staticmethod
    def execute_sell(
        code: str,
        price: float,
        shares: int,
        trade_date: date,
    ) -> tuple[Position | None, TradeAction]:
        """Atomically update position and insert REDUCE/SELL trade record."""
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
                remaining_shares = old.shares - shares
                remaining_cost = float(old.cost) * old.shares - price * shares
                old.cost = Decimal(str(round(remaining_cost / remaining_shares, 4)))
                old.shares = remaining_shares
                result = old

            session.add(TradeRecordOrm(
                code=code,
                action=action.value,
                trade_date=trade_date,
                price=Decimal(str(round(price, 4))),
                shares=shares,
            ))
            session.commit()
            return result.to_model() if result is not None else None, action
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
