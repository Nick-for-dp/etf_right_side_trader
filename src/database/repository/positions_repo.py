"""positions 表 CRUD。"""

from src.database.connection import get_session
from src.database.schema import PositionOrm
from src.models import Position


def find_all() -> list[Position]:
    """查询全部持仓记录。

    Returns:
        按 id 升序排列的 Position 列表
    """
    session = get_session()
    try:
        results = session.query(PositionOrm).order_by(PositionOrm.id.asc()).all()
        return [r.to_model() for r in results]
    finally:
        session.close()


def find_by_code(code: str) -> Position | None:
    """按 ETF 代码查询持仓。

    Args:
        code: ETF 代码

    Returns:
        Position 对象，无数据时返回 None
    """
    session = get_session()
    try:
        result = (
            session.query(PositionOrm)
            .filter(PositionOrm.code == code)
            .first()
        )
        return result.to_model() if result else None
    finally:
        session.close()


def save(pos: Position) -> Position:
    """新增或更新持仓。

    session.merge 策略：有 id 则更新现有记录，无 id 则插入新记录。

    Args:
        pos: 待保存的 Position 对象

    Returns:
        保存后的 Position（含数据库生成的 id）
    """
    session = get_session()
    try:
        orm = pos.to_orm()
        merged = session.merge(orm)
        session.commit()
        return merged.to_model()
    finally:
        session.close()


def delete_by_id(position_id: int) -> None:
    """按 id 删除持仓。

    Args:
        position_id: 持仓记录 id
    """
    session = get_session()
    try:
        session.query(PositionOrm).filter(PositionOrm.id == position_id).delete()
        session.commit()
    finally:
        session.close()
