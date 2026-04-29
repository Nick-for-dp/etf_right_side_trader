"""signals 表 CRUD。"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.connection import get_session
from src.database.schema import SignalOrm
from src.models import Signal


def save(code: str, date: date, signal: str,
         version: str, meta: dict) -> None:
    """写入或替换单日策略信号。

    ON CONFLICT DO UPDATE 策略，同一天同一 ETF 的信号会被覆盖。

    Args:
        code:    ETF 代码
        date:    信号日期
        signal:  最终信号（BUY / SELL / HOLD）
        version: 策略版本号
        meta:    信号元数据字典
    """
    session = get_session()
    try:
        stmt = pg_insert(SignalOrm).values(
            code=code, date=date, signal=signal,
            strategy_version=version, signal_meta=meta,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["code", "date"],
            set_={
                "signal": stmt.excluded.signal,
                "strategy_version": stmt.excluded.strategy_version,
                "signal_meta": stmt.excluded.signal_meta,
            },
        )
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def find_by_date(date: date) -> list[Signal]:
    """查询某日全部 ETF 的策略信号。

    Args:
        date: 信号日期

    Returns:
        按代码升序排列的 Signal 列表
    """
    session = get_session()
    try:
        results = (
            session.query(SignalOrm)
            .filter(SignalOrm.date == date)
            .order_by(SignalOrm.code.asc())
            .all()
        )
        return [r.to_model() for r in results]
    finally:
        session.close()


def find_by_code_between(code: str, start: date | None = None,
                         end: date | None = None) -> list[Signal]:
    """按 ETF 代码和日期区间查询策略信号。

    Args:
        code:  ETF 代码
        start: 起始日期（含），None 表示不限制
        end:   结束日期（含），None 表示不限制

    Returns:
        按日期升序排列的 Signal 列表
    """
    session = get_session()
    try:
        q = session.query(SignalOrm).filter(SignalOrm.code == code)
        if start is not None:
            q = q.filter(SignalOrm.date >= start)
        if end is not None:
            q = q.filter(SignalOrm.date <= end)
        return [r.to_model() for r in q.order_by(SignalOrm.date.asc()).all()]
    finally:
        session.close()
