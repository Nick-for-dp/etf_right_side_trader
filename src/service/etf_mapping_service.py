"""ETF 映射业务服务。"""

from dataclasses import dataclass

from src.config import AppConfig, EtfItem
from src.database import etf_mapping_repo
from src.models import EtfMapping


@dataclass
class EtfMappingSyncResult:
    """ETF 映射同步结果。"""

    total_config: int
    saved: int
    deleted_stale: int


class EtfMappingService:
    """ETF 映射业务服务。"""

    @staticmethod
    def build_from_config(config: AppConfig) -> list[EtfMapping]:
        """从配置构造映射列表，并校验代码唯一性。"""
        seen: set[str] = set()
        mappings: list[EtfMapping] = []
        for item in config.etf_list:
            if item.symbol in seen:
                raise ValueError(f"etf_list 存在重复 ETF 代码: {item.symbol}")
            missing = _missing_mapping_fields(item)
            if missing:
                raise ValueError(
                    f"ETF {item.symbol} 缺少映射字段: {', '.join(missing)}"
                )
            seen.add(item.symbol)
            mappings.append(_mapping_from_item(item))
        return mappings

    @classmethod
    def sync_from_config(
        cls,
        config: AppConfig,
        *,
        prune_stale: bool = True,
    ) -> EtfMappingSyncResult:
        """将 settings.yaml 中的 ETF 映射同步到 etf_mapping 表。"""
        mappings = cls.build_from_config(config)
        etf_mapping_repo.save_batch(mappings)
        deleted = (
            etf_mapping_repo.delete_not_in_symbols([m.symbol for m in mappings])
            if prune_stale else 0
        )
        return EtfMappingSyncResult(
            total_config=len(config.etf_list),
            saved=len(mappings),
            deleted_stale=deleted,
        )

    @staticmethod
    def find_all() -> list[EtfMapping]:
        """查询全部 ETF 映射。"""
        return etf_mapping_repo.find_all()

    @staticmethod
    def find_by_symbol(symbol: str) -> EtfMapping | None:
        """按 ETF 代码查询映射。"""
        return etf_mapping_repo.find_by_symbol(symbol)

    @staticmethod
    def build_symbol_name_map(mappings: list[EtfMapping] | None = None) -> dict[str, str]:
        """构造 {symbol: name} 映射。"""
        records = mappings if mappings is not None else etf_mapping_repo.find_all()
        return {record.symbol: record.name for record in records}

    @staticmethod
    def build_regime_group_map(mappings: list[EtfMapping] | None = None) -> dict[str, str]:
        """构造 {symbol: regime_group} 映射。"""
        records = mappings if mappings is not None else etf_mapping_repo.find_all()
        return {record.symbol: record.regime_group for record in records}


def _mapping_from_item(item: EtfItem) -> EtfMapping:
    return EtfMapping(
        symbol=item.symbol,
        name=item.name,
        market=item.market,
        tracking_index=item.tracking_index,
        sector=item.sector,
        theme=item.theme,
        category=item.category,
        regime_group=item.regime_group,
    )


def _missing_mapping_fields(item: EtfItem) -> list[str]:
    required = (
        "name", "market", "tracking_index",
        "sector", "theme", "category", "regime_group",
    )
    return [field for field in required if not str(getattr(item, field, "")).strip()]


def format_etf_mapping_sync_report(result: EtfMappingSyncResult) -> str:
    """格式化 ETF 映射同步结果。"""
    return (
        "ETF 映射同步完成\n"
        f"- 配置 ETF 数: {result.total_config}\n"
        f"- 写入/更新: {result.saved}\n"
        f"- 删除过期映射: {result.deleted_stale}"
    )
