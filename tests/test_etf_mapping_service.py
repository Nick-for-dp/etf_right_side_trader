"""ETF 映射服务测试。"""

import pytest

from src.config.settings_reader import AppConfig, EtfItem
from src.service import etf_mapping_service as svc


def _config(etf_list: list[EtfItem]) -> AppConfig:
    return AppConfig(
        etf_list=etf_list,
        db_url="postgresql://unused",
        strategy_type="multi_indicator_scoring",
        strategy_params={},
    )


def _etf(symbol: str = "588000") -> EtfItem:
    return EtfItem(
        symbol=symbol,
        name="科创50ETF",
        market="A股",
        tracking_index="000688",
        sector="科技",
        theme="科创50",
        category="broad",
        regime_group="A股",
    )


def test_build_from_config_keeps_mapping_fields():
    mappings = svc.EtfMappingService.build_from_config(_config([_etf()]))

    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.symbol == "588000"
    assert mapping.name == "科创50ETF"
    assert mapping.market == "A股"
    assert mapping.tracking_index == "000688"
    assert mapping.sector == "科技"
    assert mapping.theme == "科创50"
    assert mapping.category == "broad"
    assert mapping.regime_group == "A股"


def test_sync_from_config_saves_and_prunes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        svc.etf_mapping_repo,
        "save_batch",
        lambda records: calls.append(("save_batch", len(records))),
    )
    monkeypatch.setattr(
        svc.etf_mapping_repo,
        "delete_not_in_symbols",
        lambda symbols: calls.append(("delete_not_in_symbols", symbols)) or 2,
    )

    result = svc.EtfMappingService.sync_from_config(_config([_etf(), _etf("513100")]))

    assert result.total_config == 2
    assert result.saved == 2
    assert result.deleted_stale == 2
    assert calls == [
        ("save_batch", 2),
        ("delete_not_in_symbols", ["588000", "513100"]),
    ]


def test_build_from_config_rejects_duplicate_symbol():
    with pytest.raises(ValueError, match="重复 ETF 代码"):
        svc.EtfMappingService.build_from_config(_config([_etf(), _etf()]))


def test_build_from_config_rejects_incomplete_mapping():
    incomplete = _etf()
    incomplete.theme = ""

    with pytest.raises(ValueError, match="缺少映射字段: theme"):
        svc.EtfMappingService.build_from_config(_config([incomplete]))
