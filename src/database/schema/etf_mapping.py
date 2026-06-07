"""etf_mapping 表 ORM 映射。"""

from sqlalchemy import Column, PrimaryKeyConstraint, VARCHAR

from src.database.schema.base import Base
from src.models.etf_mapping import EtfMapping


class EtfMappingOrm(Base):
    """ETF 基础映射 ORM 模型。"""

    __tablename__ = "etf_mapping"

    symbol = Column[str](VARCHAR(20), nullable=False)
    name = Column[str](VARCHAR(100), nullable=False)
    market = Column[str](VARCHAR(20), nullable=False)
    tracking_index = Column[str](VARCHAR(20), nullable=False)
    sector = Column[str](VARCHAR(50), nullable=False)
    theme = Column[str](VARCHAR(100), nullable=False)
    category = Column[str](VARCHAR(20), nullable=False)
    regime_group = Column[str](VARCHAR(20), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("symbol"),
    )

    def to_model(self) -> EtfMapping:
        """转换为业务模型。"""
        return EtfMapping(
            symbol=self.symbol,
            name=self.name,
            market=self.market,
            tracking_index=self.tracking_index,
            sector=self.sector,
            theme=self.theme,
            category=self.category,
            regime_group=self.regime_group,
        )
