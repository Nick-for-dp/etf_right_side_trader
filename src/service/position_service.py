"""持仓管理业务逻辑：加仓均价重算、减仓保本价重算。"""

from datetime import date

from src.database import positions_repo
from src.models import Position


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
