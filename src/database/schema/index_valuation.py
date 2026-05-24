"""index_valuation 表 ORM 映射。

Table: index_valuation — 指数 PE/PB 历史估值
Row example: index_code="000688", date=2026-05-15, pe=42.5, pb=4.8
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Column, Date, Numeric, VARCHAR, PrimaryKeyConstraint

from src.database.schema.base import Base
from src.models.index_valuation import IndexValuation


class IndexValuationOrm(Base):
    """index_valuation 表 ORM 模型。

    以 (index_code, date) 为联合主键，存储指数每日 PE/PB 估值。
    数据源：AKShare index_value_hist_funddb 接口。
    """

    __tablename__ = "index_valuation"

    index_code = Column[str](VARCHAR(20), nullable=False)
    date = Column[date](Date, nullable=False)
    pe = Column[Decimal](Numeric[Decimal](10, 4))
    pb = Column[Decimal](Numeric[Decimal](10, 4))

    __table_args__ = (
        PrimaryKeyConstraint("index_code", "date"),
    )

    def to_model(self) -> IndexValuation:
        """转换为业务模型。"""
        return IndexValuation(
            index_code=self.index_code,
            date=self.date,
            pe=float(self.pe) if self.pe is not None else None,
            pb=float(self.pb) if self.pb is not None else None,
        )
