"""market_index_quote 表 CRUD。"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.connection import get_session
from src.database.schema import MarketIndexQuoteOrm
from src.models import MarketIndexQuote


def save_batch(records: list[MarketIndexQuote]) -> None:
    """批量写入指数行情，已存在记录则更新。

    指数日常链路可能先写入 OHLCV，后续再补齐成交额，因此这里允许
    ON CONFLICT DO UPDATE。
    """
    if not records:
        return
    session = get_session()
    try:
        orm_records = [r.to_orm() for r in records]
        stmt = pg_insert(MarketIndexQuoteOrm).values([
            {c.name: getattr(orm, c.name) for c in MarketIndexQuoteOrm.__table__.columns}
            for orm in orm_records
        ])
        stmt = stmt.on_conflict_do_update(
            index_elements=["index_code", "date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "amount": stmt.excluded.amount,
            },
        )
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def find_by_code_in_range(
    index_code: str,
    start: date | None = None,
    end: date | None = None,
) -> list[MarketIndexQuote]:
    """按指数代码和日期区间查询行情。"""
    session = get_session()
    try:
        q = session.query(MarketIndexQuoteOrm).filter(
            MarketIndexQuoteOrm.index_code == index_code
        )
        if start is not None:
            q = q.filter(MarketIndexQuoteOrm.date >= start)
        if end is not None:
            q = q.filter(MarketIndexQuoteOrm.date <= end)
        return [r.to_model() for r in q.order_by(MarketIndexQuoteOrm.date.asc()).all()]
    finally:
        session.close()


def find_latest_date(index_code: str) -> date | None:
    """查询某指数最新行情日期。"""
    session = get_session()
    try:
        result = (
            session.query(MarketIndexQuoteOrm.date)
            .filter(MarketIndexQuoteOrm.index_code == index_code)
            .order_by(MarketIndexQuoteOrm.date.desc())
            .first()
        )
        return result[0] if result else None
    finally:
        session.close()
