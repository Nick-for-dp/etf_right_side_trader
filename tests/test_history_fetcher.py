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
