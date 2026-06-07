"""历史数据抓取器单元测试。"""

from datetime import date

import pandas as pd

from src.fetcher.history_fetcher import HistoryFetcher


class _FakePro:
    def index_daily(self, **kwargs):
        assert kwargs["ts_code"] == "000300.SH"
        assert kwargs["fields"] == "trade_date,open,high,low,close,vol,amount"
        return pd.DataFrame([{
            "trade_date": "20240102",
            "open": "3500.1",
            "high": "3510.2",
            "low": "3490.3",
            "close": "3505.4",
            "vol": "12345.6",
            "amount": "98765.4",
        }])

    def index_global(self, **kwargs):
        assert kwargs["ts_code"] == "HKTECH"
        assert kwargs["start_date"] == "20260501"
        assert kwargs["end_date"] == "20260531"
        return pd.DataFrame([{
            "ts_code": "HKTECH",
            "trade_date": "20260529",
            "open": "4939.91",
            "close": "4884.23",
            "high": "4980.78",
            "low": "4867.56",
            "vol": None,
        }])


def test_get_index_history_from_tushare_matches_market_index_quote_shape():
    """指数历史数据应转换为 market_index_quote 可直接消费的字段和单位。"""
    fetcher = object.__new__(HistoryFetcher)
    fetcher.pro = _FakePro()

    df = fetcher.get_index_history_from_tushare("000300", "20240101", "20240131")

    assert df is not None
    assert df.columns.tolist() == [
        "index_code", "date", "open", "high", "low", "close", "volume", "amount"
    ]
    row = df.iloc[0]
    assert row["index_code"] == "000300"
    assert row["date"] == date(2024, 1, 2)
    assert row["volume"] == 1234560.0
    assert row["amount"] == 98765400.0


def test_get_global_index_history_from_tushare_matches_market_index_quote_shape():
    """全球指数历史数据应转换为 market_index_quote 字段，允许量额为空。"""
    fetcher = object.__new__(HistoryFetcher)
    fetcher.pro = _FakePro()

    df = fetcher.get_global_index_history_from_tushare(
        "HZ5017",
        "20260501",
        "20260531",
        tushare_code="HKTECH",
    )

    assert df is not None
    assert df.columns.tolist() == [
        "index_code", "date", "open", "high", "low", "close", "volume", "amount"
    ]
    row = df.iloc[0]
    assert row["index_code"] == "HZ5017"
    assert row["date"] == date(2026, 5, 29)
    assert row["open"] == 4939.91
    assert row["high"] == 4980.78
    assert row["low"] == 4867.56
    assert row["close"] == 4884.23
    assert pd.isna(row["volume"])
    assert row["amount"] is None
