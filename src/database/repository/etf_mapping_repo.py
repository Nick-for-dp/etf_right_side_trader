"""etf_mapping 表 CRUD。"""

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.connection import get_session
from src.database.schema import EtfMappingOrm
from src.models import EtfMapping


def save_batch(records: list[EtfMapping]) -> None:
    """批量写入或更新 ETF 映射。"""
    if not records:
        return
    session = get_session()
    try:
        orm_records = [record.to_orm() for record in records]
        values = [
            {c.name: getattr(orm, c.name) for c in EtfMappingOrm.__table__.columns}
            for orm in orm_records
        ]
        stmt = pg_insert(EtfMappingOrm).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                "name": stmt.excluded.name,
                "market": stmt.excluded.market,
                "tracking_index": stmt.excluded.tracking_index,
                "sector": stmt.excluded.sector,
                "theme": stmt.excluded.theme,
                "category": stmt.excluded.category,
                "regime_group": stmt.excluded.regime_group,
            },
        )
        session.execute(stmt)
        session.commit()
    finally:
        session.close()


def find_all() -> list[EtfMapping]:
    """查询全部 ETF 映射。"""
    session = get_session()
    try:
        rows = session.query(EtfMappingOrm).order_by(EtfMappingOrm.symbol.asc()).all()
        return [row.to_model() for row in rows]
    finally:
        session.close()


def find_by_symbol(symbol: str) -> EtfMapping | None:
    """按 ETF 代码查询映射。"""
    session = get_session()
    try:
        row = (
            session.query(EtfMappingOrm)
            .filter(EtfMappingOrm.symbol == symbol)
            .first()
        )
        return row.to_model() if row else None
    finally:
        session.close()


def find_by_symbols(symbols: list[str]) -> list[EtfMapping]:
    """按 ETF 代码列表查询映射。"""
    if not symbols:
        return []
    session = get_session()
    try:
        rows = (
            session.query(EtfMappingOrm)
            .filter(EtfMappingOrm.symbol.in_(symbols))
            .order_by(EtfMappingOrm.symbol.asc())
            .all()
        )
        return [row.to_model() for row in rows]
    finally:
        session.close()


def delete_not_in_symbols(symbols: list[str]) -> int:
    """删除不在当前配置 ETF 列表中的映射，返回删除行数。"""
    session = get_session()
    try:
        q = session.query(EtfMappingOrm)
        if symbols:
            q = q.filter(~EtfMappingOrm.symbol.in_(symbols))
        deleted = q.delete(synchronize_session=False)
        session.commit()
        return int(deleted or 0)
    finally:
        session.close()
