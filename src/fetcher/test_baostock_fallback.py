"""测试 BaoStock 故障处理以及 AKShare、东方财富备用链路。"""

from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd

import src.fetcher.daily_fetcher as daily_module
import src.fetcher.market_index_fetcher as market_index_module
from src.config.settings_reader import MarketIndexItem
from src.fetcher import baostock_session as session_module
from src.fetcher.baostock_session import BaoStockUnavailable
from src.fetcher.daily_fetcher import DailyFetcher
from src.fetcher.market_index_fetcher import MarketIndexFetcher


def test_baostock_session_captures_upstream_socket_error_and_opens_circuit(
    monkeypatch, capsys
):
    calls = 0

    def failed_login():
        nonlocal calls
        calls += 1
        print("服务器连接失败，请稍后再试。")
        print("[WinError 10057] socket is not connected")
        return SimpleNamespace(error_code="10002007", error_msg="网络接收错误。")

    session_module.reset_baostock_circuit()
    monkeypatch.setattr(session_module.bs, "login", failed_login)

    for _ in range(2):
        try:
            with session_module.baostock_session(cooldown=60):
                pass
        except BaoStockUnavailable:
            pass

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert calls == 1
    session_module.reset_baostock_circuit()


def test_daily_fetcher_falls_back_to_eastmoney_when_baostock_is_down(monkeypatch):
    fetcher = DailyFetcher()
    fallback = pd.DataFrame([{
        "trade_date": "2026-07-10",
        "symbol": "588000",
        "open_px": 1.0,
        "high_px": 1.1,
        "low_px": 0.9,
        "close_px": 1.05,
        "volume": 100,
    }])

    @contextmanager
    def unavailable_session():
        raise BaoStockUnavailable("test outage")
        yield

    monkeypatch.setattr(daily_module, "baostock_session", unavailable_session)
    monkeypatch.setattr(fetcher, "get_etf_daily_from_eastmoney", lambda *args: fallback)
    monkeypatch.setattr(fetcher, "get_etf_metric_from_eastmoney", lambda *args: None)

    result = fetcher.fetch_daily("588000", "2026-07-10", "2026-07-10")

    assert result.iloc[0]["code"] == "588000"
    assert result.iloc[0]["close"] == 1.05


def test_market_index_fetcher_falls_back_when_baostock_is_down(monkeypatch):
    fetcher = MarketIndexFetcher()
    index = MarketIndexItem(
        code="000300",
        baostock_code="sh.000300",
        akshare_symbol="sh000300",
        source="baostock",
    )
    fallback = pd.DataFrame([{"index_code": "000300", "close": 3500.0}])

    @contextmanager
    def unavailable_session():
        raise BaoStockUnavailable("test outage")
        yield

    monkeypatch.setattr(market_index_module, "baostock_session", unavailable_session)
    monkeypatch.setattr(fetcher, "_fetch_from_akshare", lambda *args: fallback)

    result = fetcher.fetch_daily(index, "2026-07-01", "2026-07-10")

    assert result.equals(fallback)
