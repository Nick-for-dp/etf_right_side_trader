"""quote 表 CRUD。"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.connection import get_session
from src.database.schema import QuoteOrm
from src.models import Quote


def save_batch(records: list[Quote]) -> None:
    """批量写入行情记录。

    按 (code, date) 主键去重（ON CONFLICT DO NOTHING），已存在的记录不会被覆盖。

    Args:
        records: 待写入的 Quote 列表，空列表时直接返回
    """
    if not records:
        return
    session = get_session()
    try:
        orm_records = [r.to_orm() for r in records]
        stmt = pg_insert(QuoteOrm).values([
            {c.name: getattr(orm, c.name) for c in QuoteOrm.__table__.columns}
            for orm in orm_records
        ])
        stmt = stmt.on_conflict_do_nothing()
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def find_by_code_in_range(code: str, start: date | None = None,
                         end: date | None = None) -> list[Quote]:
    """按 ETF 代码和日期区间查询行情。

    Args:
        code:  ETF 代码，如 "588000"
        start: 起始日期（含），None 表示不限制
        end:   结束日期（含），None 表示不限制

    Returns:
        按日期升序排列的 Quote 列表，无数据时返回空列表
    """
    session = get_session()
    try:
        q = session.query(QuoteOrm).filter(QuoteOrm.code == code)
        if start is not None:
            q = q.filter(QuoteOrm.date >= start)
        if end is not None:
            q = q.filter(QuoteOrm.date <= end)
        return [r.to_model() for r in q.order_by(QuoteOrm.date.asc()).all()]
    finally:
        session.close()


def find_latest_date(code: str) -> date | None:
    """查询某 ETF 最新的行情日期。

    Args:
        code: ETF 代码

    Returns:
        最新行情日期，无数据时返回 None
    """
    session = get_session()
    try:
        result = (
            session.query(QuoteOrm.date)
            .filter(QuoteOrm.code == code)
            .order_by(QuoteOrm.date.desc())
            .first()
        )
        return result[0] if result else None
    finally:
        session.close()


def find_latest_quote(code: str) -> Quote | None:
    """查询某 ETF 最新一条完整行情记录。

    Args:
        code: ETF 代码

    Returns:
        最新 Quote 对象，无数据时返回 None
    """
    session = get_session()
    try:
        result = (
            session.query(QuoteOrm)
            .filter(QuoteOrm.code == code)
            .order_by(QuoteOrm.date.desc())
            .first()
        )
        return result.to_model() if result else None
    finally:
        session.close()
