"""operation_advice 表 CRUD。"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.connection import get_session
from src.database.schema import OperationAdviceOrm
from src.models import OperationAdvice


def save_batch(records: list[OperationAdvice]) -> None:
    """批量写入操作建议。

    ON CONFLICT DO NOTHING 策略，已存在的记录不会被覆盖。

    Args:
        records: 待写入的 OperationAdvice 列表，空列表时直接返回
    """
    if not records:
        return
    session = get_session()
    try:
        orm_records = [r.to_orm() for r in records]
        stmt = pg_insert(OperationAdviceOrm).values([
            {c.name: getattr(orm, c.name) for c in OperationAdviceOrm.__table__.columns}
            for orm in orm_records
        ])
        stmt = stmt.on_conflict_do_nothing()
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def find_by_code(code: str) -> list[OperationAdvice]:
    """按 ETF 代码查询全部操作建议。

    Args:
        code: ETF 代码

    Returns:
        按日期升序排列的 OperationAdvice 列表
    """
    session = get_session()
    try:
        q = session.query(OperationAdviceOrm).filter(OperationAdviceOrm.code == code)
        return [r.to_model() for r in q.order_by(OperationAdviceOrm.date.asc()).all()]
    finally:
        session.close()


def find_by_date(date: date) -> list[OperationAdvice]:
    """查询某日全部操作建议。

    Args:
        date: 建议日期

    Returns:
        按代码升序排列的 OperationAdvice 列表
    """
    session = get_session()
    try:
        results = (
            session.query(OperationAdviceOrm)
            .filter(OperationAdviceOrm.date == date)
            .order_by(OperationAdviceOrm.code.asc())
            .all()
        )
        return [r.to_model() for r in results]
    finally:
        session.close()
