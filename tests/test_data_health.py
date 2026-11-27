"""数据健康检查：指数按所属市场日历校验最新交易日。"""

from datetime import date

from src.config.settings_reader import MarketIndexItem
from src.database.data_health import _index_expected_date


def _idx(source: str) -> MarketIndexItem:
    return MarketIndexItem(code="NDX", name="纳指100", source=source, weight=0.0)


def test_us_index_uses_us_calendar_on_a_share_only_day():
    """2026-11-26 美股感恩节休市，A 股正常交易：美股指数仍应停在 11-25。"""
    expected = _index_expected_date(_idx("akshare_us"), date(2026, 11, 27), date(2026, 11, 26))
    assert expected == date(2026, 11, 25)


def test_a_share_index_keeps_a_share_calendar():
    fallback = date(2026, 11, 26)
    assert _index_expected_date(_idx("baostock"), date(2026, 11, 27), fallback) == fallback
