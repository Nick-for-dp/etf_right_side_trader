"""市场宽基指数日线采集器。"""

from datetime import date
from typing import Any

import akshare as ak
import baostock as bs
import pandas as pd
import requests
from requests import RequestException

from src.config.settings_reader import MarketIndexItem
from src.utils import get_logger, rate_limit, retry_on_error

logger = get_logger(__name__)


class MarketIndexFetcher:
    """采集宽基指数 OHLCV 和成交额。

    日常链路优先使用 BaoStock。BaoStock 缺口（当前主要是科创50）使用
    AKShare 的新浪指数日线补 OHLCV，并尝试东方财富补成交额。
    """

    GOOD_STATUS_CODE = "0"

    def fetch_daily(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """拉取单个指数日线行情。

        Args:
            index: 指数配置项
            start_date: 起始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD

        Returns:
            columns = [index_code, date, open, high, low, close, volume, amount]
        """
        if index.source in {"auto", "baostock"} and index.baostock_code:
            df = self._fetch_from_baostock(index, start_date, end_date)
            if not df.empty:
                return df
            if index.source == "baostock":
                logger.warning(f"BaoStock 未返回 {index.code}，尝试 AKShare 兜底")

        if index.akshare_symbol:
            return self._fetch_from_akshare(index, start_date, end_date)

        logger.warning(f"{index.code} 未配置可用指数数据源")
        return pd.DataFrame()

    @rate_limit(min_interval=6.0, key="baostock_index")
    @retry_on_error(max_retries=3, retry_delay=5.0)
    def _fetch_from_baostock(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """从 BaoStock 获取指数 OHLCV + 成交额。"""
        lg = bs.login()
        if lg.error_code != self.GOOD_STATUS_CODE:
            raise RequestException(f"登录 BaoStock 失败: {lg.error_code} {lg.error_msg}")

        try:
            fields = "date,code,open,high,low,close,volume,amount"
            rs = bs.query_history_k_data_plus(
                code=index.baostock_code,
                fields=fields,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
            )
            if rs.error_code != self.GOOD_STATUS_CODE:
                raise RequestException(
                    f"查询 BaoStock 失败: {rs.error_code} {rs.error_msg}"
                )

            rows: list[dict[str, Any]] = []
            while rs.next():
                row = rs.get_row_data()
                rows.append({
                    "index_code": index.code,
                    "date": row[0],
                    "open": _to_float(row[2]),
                    "high": _to_float(row[3]),
                    "low": _to_float(row[4]),
                    "close": _to_float(row[5]),
                    "volume": _to_float(row[6]),
                    "amount": _to_float(row[7]),
                })
            logger.info(
                f"BaoStock 指数 {index.code} {start_date}~{end_date} 返回 {len(rows)} 条"
            )
            return pd.DataFrame(rows)
        finally:
            bs.logout()

    @rate_limit(min_interval=8.0, key="akshare_index")
    @retry_on_error(max_retries=3, retry_delay=8.0)
    def _fetch_from_akshare(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """从 AKShare 获取指数 OHLCV，并尽力补成交额。"""
        raw_df = ak.stock_zh_index_daily(symbol=index.akshare_symbol)
        if raw_df is None or raw_df.empty:
            logger.warning(f"AKShare 未返回 {index.code} 指数行情")
            return pd.DataFrame()

        raw_df = raw_df.copy()
        raw_df["date"] = pd.to_datetime(raw_df["date"]).dt.date
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        raw_df = raw_df[(raw_df["date"] >= start) & (raw_df["date"] <= end)]
        if raw_df.empty:
            return pd.DataFrame()

        result = raw_df.rename(columns={"date": "date"})[
            ["date", "open", "high", "low", "close", "volume"]
        ].copy()
        result["index_code"] = index.code
        result["amount"] = None

        amount_map = self._fetch_amount_from_eastmoney(index, start_date, end_date)
        if amount_map:
            result["amount"] = result["date"].map(amount_map)

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            result[col] = pd.to_numeric(result[col], errors="coerce")

        logger.info(
            f"AKShare 指数 {index.code} {start_date}~{end_date} 返回 {len(result)} 条"
        )
        return result[[
            "index_code", "date", "open", "high", "low", "close", "volume", "amount"
        ]]

    @rate_limit(min_interval=8.0, key="eastmoney_index_amount")
    def _fetch_amount_from_eastmoney(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> dict[date, float]:
        """从东方财富补充成交额；失败时返回空映射，不阻断主行情。"""
        secid = _eastmoney_secid(index)
        if not secid:
            return {}

        try:
            start_fmt = start_date.replace("-", "")
            end_fmt = end_date.replace("-", "")
            params = {
                "secid": secid,
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",
                "fqt": "0",
                "beg": start_fmt,
                "end": end_fmt,
            }
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            }
            response = requests.get(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params=params,
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            rows = data.get("klines") or []
            amount_map: dict[date, float] = {}
            for item in rows:
                parts = item.split(",")
                if len(parts) >= 7:
                    amount_map[date.fromisoformat(parts[0])] = _to_float(parts[6])
            return amount_map
        except Exception as exc:
            logger.warning(f"东方财富成交额补充失败 index={index.code}: {exc}")
            return {}


def _to_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _eastmoney_secid(index: MarketIndexItem) -> str:
    symbol = index.akshare_symbol or ""
    if symbol.startswith("sh"):
        return f"1.{symbol[2:]}"
    if symbol.startswith("sz"):
        return f"0.{symbol[2:]}"
    return ""
