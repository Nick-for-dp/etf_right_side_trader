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

    # ── 源派发器：按 source 字段分发到对应采集方法 ──
    # 新增数据源类型只需在此注册，无需修改 fetch_daily
    SOURCE_DISPATCH = {
        "baostock": "_fetch_from_baostock",
        "akshare": "_fetch_from_akshare",
        "akshare_us": "_fetch_us_index_from_akshare",
        "akshare_hk": "_fetch_hk_index_from_akshare",
        "tushare_global": "_fetch_global_index_from_tushare",
    }

    def fetch_daily(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """拉取单个指数日线行情。

        按 index.source 分发到对应采集方法。新增数据源类型只需在
        SOURCE_DISPATCH 中注册，无需修改此方法。

        Args:
            index: 指数配置项
            start_date: 起始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD

        Returns:
            columns = [index_code, date, open, high, low, close, volume, amount]
        """
        source = index.source

        # baostock 有兜底逻辑：BaoStock 无数据时回退 AKShare
        if source in {"auto", "baostock"} and index.baostock_code:
            df = self._fetch_from_baostock(index, start_date, end_date)
            if not df.empty:
                return df
            if source == "baostock":
                logger.warning(f"BaoStock 未返回 {index.code}，尝试 AKShare 兜底")
            # 兜底：走 AKShare 新浪源
            if index.akshare_symbol:
                return self._fetch_from_akshare(index, start_date, end_date)
            return pd.DataFrame()

        # 按 SOURCE_DISPATCH 分发
        method_name = self.SOURCE_DISPATCH.get(source)
        if method_name is None:
            logger.warning(f"未知数据源类型: {source}（{index.code}），可用: {list(self.SOURCE_DISPATCH.keys())}")
            return pd.DataFrame()

        method = getattr(self, method_name, None)
        if method is None:
            logger.warning(f"未实现的分发方法: {method_name}（{index.code}）")
            return pd.DataFrame()

        return method(index, start_date, end_date)

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
    @retry_on_error(max_retries=2, retry_delay=8.0)
    def _fetch_from_akshare(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """从 AKShare 获取指数 OHLCV，并尽力补成交额。

        部分中证行业指数在 Sina 源上可能无数据或格式不兼容，
        失败时返回空 DataFrame 交由上游处理。
        """
        try:
            raw_df = ak.stock_zh_index_daily(symbol=index.akshare_symbol)
        except Exception as exc:
            logger.warning(f"AKShare 指数 {index.code}({index.akshare_symbol}) 拉取异常: {exc}")
            return pd.DataFrame()
        if raw_df is None or raw_df.empty:
            logger.warning(f"AKShare 未返回 {index.code}({index.akshare_symbol}) 指数行情")
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

    @rate_limit(min_interval=8.0, key="akshare_us")
    @retry_on_error(max_retries=3, retry_delay=8.0)
    def _fetch_us_index_from_akshare(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """从 AKShare 获取美股指数日线行情（如 NDX、SPX）。

        AKShare 的 stock_us_index_daily 返回美股指数历史日线全量数据，
        包含 date/open/high/low/close/volume。
        本方法拉取全量后在本地切片，幂等写入由 save_batch 的 ON CONFLICT 保证。

        Args:
            index: 指数配置项，akshare_symbol 填写 AKShare 接受的代码（如 "ndx"）
            start_date: 起始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD

        Returns:
            columns = [index_code, date, open, high, low, close, volume, amount]
        """
        symbol = index.akshare_symbol
        if not symbol:
            logger.warning(f"美股指数 {index.code} 未配置 akshare_symbol")
            return pd.DataFrame()

        # 补齐新浪所需的 "." 前缀（如 ndx → .NDX）
        sina_symbol = f".{symbol.upper()}" if not symbol.startswith(".") else symbol.upper()

        try:
            raw_df = ak.index_us_stock_sina(symbol=sina_symbol)
        except Exception as exc:
            logger.warning(f"AKShare 美股指数 {sina_symbol} 拉取失败: {exc}")
            return pd.DataFrame()

        if raw_df is None or raw_df.empty:
            logger.warning(f"AKShare 未返回美股指数 {sina_symbol}")
            return pd.DataFrame()

        raw_df = raw_df.copy()
        raw_df["date"] = pd.to_datetime(raw_df["date"]).dt.date
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        raw_df = raw_df[(raw_df["date"] >= start) & (raw_df["date"] <= end)]
        if raw_df.empty:
            return pd.DataFrame()

        result = raw_df[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
        result["index_code"] = index.code

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            result[col] = pd.to_numeric(result[col], errors="coerce")

        logger.info(
            f"AKShare 美股 {index.code} {start_date}~{end_date} 返回 {len(result)} 条"
        )
        return result[[
            "index_code", "date", "open", "high", "low", "close", "volume", "amount"
        ]]

    @rate_limit(min_interval=8.0, key="akshare_hk")
    @retry_on_error(max_retries=3, retry_delay=8.0)
    def _fetch_hk_index_from_akshare(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """从 AKShare 获取港股指数日线行情（如恒生科技 HSTECH）。

        使用新浪港股指数日线接口 stock_hk_index_daily_sina，
        返回 date/open/high/low/close/volume。
        幂等写入由 save_batch 的 ON CONFLICT 保证。

        Args:
            index: 指数配置项，akshare_symbol 填写新浪代码（如 "HSTECH"）
            start_date: 起始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD

        Returns:
            columns = [index_code, date, open, high, low, close, volume, amount]
        """
        symbol = index.akshare_symbol
        if not symbol:
            logger.warning(f"港股指数 {index.code} 未配置 akshare_symbol")
            return pd.DataFrame()

        try:
            raw_df = ak.stock_hk_index_daily_sina(symbol=symbol)
        except Exception as exc:
            logger.warning(f"AKShare 港股指数 {symbol} 拉取失败: {exc}")
            return pd.DataFrame()

        if raw_df is None or raw_df.empty:
            logger.warning(f"AKShare 未返回港股指数 {symbol}")
            return pd.DataFrame()

        raw_df = raw_df.copy()
        raw_df["date"] = pd.to_datetime(raw_df["date"]).dt.date
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        raw_df = raw_df[(raw_df["date"] >= start) & (raw_df["date"] <= end)]
        if raw_df.empty:
            return pd.DataFrame()

        result = raw_df[["date", "open", "high", "low", "close", "volume"]].copy()
        result["index_code"] = index.code
        result["amount"] = None

        for col in ["open", "high", "low", "close", "volume"]:
            result[col] = pd.to_numeric(result[col], errors="coerce")

        logger.info(
            f"AKShare 港股 {index.code} {start_date}~{end_date} 返回 {len(result)} 条"
        )
        return result[[
            "index_code", "date", "open", "high", "low", "close", "volume", "amount"
        ]]

    @rate_limit(min_interval=2.0, key="tushare")
    @retry_on_error(max_retries=2, retry_delay=5.0)
    def _fetch_global_index_from_tushare(
        self,
        index: MarketIndexItem,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """从 Tushare index_global 获取全球指数日线行情。"""
        if not index.tushare_code:
            logger.warning(f"全球指数 {index.code} 未配置 tushare_code")
            return pd.DataFrame()

        try:
            from src.fetcher.history_fetcher import HistoryFetcher

            fetcher = HistoryFetcher()
            df = fetcher.get_global_index_history_from_tushare(
                index.code,
                start_date.replace("-", ""),
                end_date.replace("-", ""),
                tushare_code=index.tushare_code,
            )
        except Exception as exc:
            logger.warning(f"Tushare 全球指数 {index.code}({index.tushare_code}) 拉取失败: {exc}")
            return pd.DataFrame()

        return df if df is not None else pd.DataFrame()

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
