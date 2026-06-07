"""ETF 基础映射业务模型。"""

from pydantic import BaseModel


class EtfMapping(BaseModel):
    """ETF 到市场、行业与跟踪指数的映射。"""

    symbol: str
    name: str
    market: str
    tracking_index: str
    sector: str
    theme: str
    category: str
    regime_group: str

    def to_orm(self):
        """转换为 ORM 对象。"""
        from src.database.schema.etf_mapping import EtfMappingOrm

        return EtfMappingOrm(
            symbol=self.symbol,
            name=self.name,
            market=self.market,
            tracking_index=self.tracking_index,
            sector=self.sector,
            theme=self.theme,
            category=self.category,
            regime_group=self.regime_group,
        )
