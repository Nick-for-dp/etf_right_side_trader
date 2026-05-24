"""指数估值业务模型。

用于存储指数 PE/PB 历史数据，供估值分位子信号（S_fund）计算使用。

Example:
    IndexValuation(index_code="000688", date=date(2026,5,15),
                   pe=42.5, pb=4.8)
"""

import math
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class IndexValuation(BaseModel):
    """指数 PE/PB 估值快照。

    index_code: 指数代码，如 "000688"（科创50）
    pe:         市盈率，TTM 口径
    pb:         市净率，LF 口径
    """

    index_code: str
    date: date
    pe: float | None = None
    pb: float | None = None

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.index_valuation import IndexValuationOrm

        pe_val = self.pe
        if pe_val is not None and isinstance(pe_val, float) and math.isnan(pe_val):
            pe_val = None

        pb_val = self.pb
        if pb_val is not None and isinstance(pb_val, float) and math.isnan(pb_val):
            pb_val = None

        return IndexValuationOrm(
            index_code=self.index_code,
            date=self.date,
            pe=Decimal(str(pe_val)) if pe_val is not None else None,
            pb=Decimal(str(pb_val)) if pb_val is not None else None,
        )
