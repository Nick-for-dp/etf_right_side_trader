"""trade_records 表 CRUD。"""

from datetime import date

from src.database.connection import get_session
from src.database.schema import TradeRecordOrm
from src.models import TradeAction, TradeRecord

_BUY_ACTIONS = (TradeAction.BUY.value, TradeAction.ADD.value)


def save(record: TradeRecord) -> TradeRecord:
    """保存单笔真实交易记录。"""
    session = get_session()
    try:
        orm = record.to_orm()
        session.add(orm)
        session.commit()
        return orm.to_model()
    finally:
        session.close()


def find_by_code(code: str) -> list[TradeRecord]:
    """按 ETF 代码查询真实交易记录，按交易日升序返回。"""
    session = get_session()
    try:
        results = (
            session.query(TradeRecordOrm)
            .filter(TradeRecordOrm.code == code)
            .order_by(TradeRecordOrm.trade_date.asc(), TradeRecordOrm.id.asc())
            .all()
        )
        return [r.to_model() for r in results]
    finally:
        session.close()


def find_latest_buy_date(code: str, as_of: date | None = None) -> date | None:
    """查询某 ETF 最近一次建仓/加仓日期。

    Args:
        code: ETF 代码
        as_of: 查询截止日期，None 表示不限制
    """
    session = get_session()
    try:
        q = (
            session.query(TradeRecordOrm.trade_date)
            .filter(TradeRecordOrm.code == code)
            .filter(TradeRecordOrm.action.in_(_BUY_ACTIONS))
        )
        if as_of is not None:
            q = q.filter(TradeRecordOrm.trade_date <= as_of)
        result = q.order_by(
            TradeRecordOrm.trade_date.desc(),
            TradeRecordOrm.id.desc(),
        ).first()
        return result[0] if result else None
    finally:
        session.close()


def count_adds(code: str, as_of: date | None = None) -> int:
    """Count ADD records for one ETF up to the optional date."""
    session = get_session()
    try:
        q = (
            session.query(TradeRecordOrm)
            .filter(TradeRecordOrm.code == code)
            .filter(TradeRecordOrm.action == TradeAction.ADD.value)
        )
        if as_of is not None:
            q = q.filter(TradeRecordOrm.trade_date <= as_of)
        return q.count()
    finally:
        session.close()
