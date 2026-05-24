"""index_valuation 表 CRUD。

为估值分位子信号（S_fund）提供指数 PE/PB 历史数据的读写访问。
"""

from datetime import date

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.connection import get_session
from src.database.schema import IndexValuationOrm
from src.models import IndexValuation


def save_batch(records: list[IndexValuation]) -> None:
    """批量写入指数估值记录。

    按 (index_code, date) 主键去重（ON CONFLICT DO NOTHING），
    已存在的记录不会被覆盖——估值历史数据一经发布不应变更。

    Args:
        records: 待写入的 IndexValuation 列表，空列表时直接返回
    """
    if not records:
        return
    session = get_session()
    try:
        orm_records = [r.to_orm() for r in records]
        stmt = pg_insert(IndexValuationOrm).values([
            {c.name: getattr(orm, c.name) for c in IndexValuationOrm.__table__.columns}
            for orm in orm_records
        ])
        stmt = stmt.on_conflict_do_nothing()
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def find_by_index_in_range(index_code: str, start: date | None = None,
                           end: date | None = None) -> list[IndexValuation]:
    """按指数代码和日期区间查询估值记录。

    Args:
        index_code: 指数代码，如 "000688"（科创50）
        start:      起始日期（含），None 表示不限制
        end:        结束日期（含），None 表示不限制

    Returns:
        按日期升序排列的 IndexValuation 列表，无数据时返回空列表
    """
    session = get_session()
    try:
        q = session.query(IndexValuationOrm).filter(
            IndexValuationOrm.index_code == index_code
        )
        if start is not None:
            q = q.filter(IndexValuationOrm.date >= start)
        if end is not None:
            q = q.filter(IndexValuationOrm.date <= end)
        return [
            r.to_model()
            for r in q.order_by(IndexValuationOrm.date.asc()).all()
        ]
    finally:
        session.close()


def find_latest_date(index_code: str) -> date | None:
    """查询某指数最新的估值日期。

    用于增量同步时判断数据覆盖到哪天，避免重复拉取。

    Args:
        index_code: 指数代码

    Returns:
        最新估值日期，无数据时返回 None
    """
    session = get_session()
    try:
        result = (
            session.query(IndexValuationOrm.date)
            .filter(IndexValuationOrm.index_code == index_code)
            .order_by(IndexValuationOrm.date.desc())
            .first()
        )
        return result[0] if result else None
    finally:
        session.close()


def count_between(index_code: str, start: date, end: date) -> int:
    """统计区间内估值记录数。

    用于判断 PE/PB 历史数据完整度，决定是否需要回填。

    Args:
        index_code: 指数代码
        start:      起始日期（含）
        end:        结束日期（含）

    Returns:
        区间内记录条数
    """
    session = get_session()
    try:
        return (
            session.query(func.count())
            .filter(IndexValuationOrm.index_code == index_code)
            .filter(IndexValuationOrm.date >= start)
            .filter(IndexValuationOrm.date <= end)
            .scalar()
        )
    finally:
        session.close()
