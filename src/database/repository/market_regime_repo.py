"""market_regime 表 CRUD。"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.connection import get_session
from src.database.schema import MarketRegimeOrm
from src.models import MarketRegime


def save(record: MarketRegime) -> None:
    """写入或覆盖单日市场热度快照。"""
    session = get_session()
    try:
        orm = record.to_orm()
        values = {c.name: getattr(orm, c.name) for c in MarketRegimeOrm.__table__.columns}
        stmt = pg_insert(MarketRegimeOrm).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={
                "state": values["state"],
                "score": values["score"],
                "data": values["data"],
            },
        )
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def find_by_date(target_date: date) -> MarketRegime | None:
    """按日期查询市场热度快照。"""
    session = get_session()
    try:
        result = (
            session.query(MarketRegimeOrm)
            .filter(MarketRegimeOrm.date == target_date)
            .first()
        )
        return result.to_model() if result else None
    finally:
        session.close()


def find_between(start: date | None = None, end: date | None = None) -> list[MarketRegime]:
    """按日期区间查询市场热度快照。"""
    session = get_session()
    try:
        q = session.query(MarketRegimeOrm)
        if start is not None:
            q = q.filter(MarketRegimeOrm.date >= start)
        if end is not None:
            q = q.filter(MarketRegimeOrm.date <= end)
        return [r.to_model() for r in q.order_by(MarketRegimeOrm.date.asc()).all()]
    finally:
        session.close()
