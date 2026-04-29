"""技术指标业务模型。

Example:
    Indicators(code="588000", date=date(2026,4,25),
               data={"ma20": 1.234, "ma60": 1.198})
"""

from datetime import date

from pydantic import BaseModel


class Indicators(BaseModel):
    """单日技术指标快照。

    data: JSON 键值对，key 为指标名，value 为标量值。
          MVP:  {"ma20", "ma60"}
          v1.1: {"dif", "dea", "macd_hist"}
          v2.0: {"bb_upper", "bb_lower", "vol_ratio", "score", ...}
    """
    code: str
    date: date
    data: dict = {}

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.indicators import IndicatorsOrm
        return IndicatorsOrm(
            code=self.code,
            date=self.date,
            data=self.data,
        )
