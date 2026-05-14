import akshare as ak
import baostock as bs
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict, Any

from .base import BaseFetcher
from src.utils import get_logger, rate_limit, retry_on_error


logger = get_logger(__name__)


class DailyFetcher(BaseFetcher):
    """通过 BaoStock与AKShare 拉取 ETF 日线行情。"""

    def __init__(self):
        super().__init__()
        self.GOOD_STATUS_CODE = "0"

    @staticmethod
    def _build_hist_data_list(
        df,
        symbol: str,
        column_map: Dict[str, str],
        date_field_name: str = "日期"
    ) -> List[Dict[str, Any]]:
        """从 DataFrame 按日期构建历史记录列表，每条记录含 trade_date/symbol 及映射字段。"""
        raw_hist_dict = df.set_index(date_field_name).to_dict(orient="index")
        hist_list = []
        for trade_date, row in raw_hist_dict.items():
            item = {"trade_date": trade_date, "symbol": symbol}
            for out_key, col_name in column_map.items():
                item[out_key] = row.get(col_name)
            hist_list.append(item)
        return hist_list
    
    @rate_limit(min_interval=6.0, key="akshare")
    @retry_on_error(max_retries=3, retry_delay=8.0)
    def get_etf_metric_from_eastmoney(
        self,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """从东方财富网获取 ETF 的单位净值指标。

        Args:
            symbol: ETF代码
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"

        Returns:
            包含 trade_date/symbol/nav 列的 DataFrame，无数据时返回 None

        Example:
            >>> fetcher = DailyFetcher()
            >>> df = fetcher.get_etf_metric_from_eastmoney("159227", "20260401", "20260428")
            >>> print(df.columns.tolist())
            ['trade_date', 'symbol', 'nav']
        """
        if not end_date:
            end_date = datetime.today().strftime("%Y%m%d")

        try:
            raw_df = ak.fund_etf_fund_info_em(fund=symbol, start_date=start_date, end_date=end_date)

            if raw_df.empty or raw_df is None:
                logger.warning(f"获取{symbol} {start_date} 至 {end_date} 的单位净值数据为空。")
                return None

            required_columns = {"净值日期", "单位净值"}
            missing_columns = required_columns - set[Any](raw_df.columns)

            if missing_columns:
                logger.warning(f"获取{symbol} {start_date} 至 {end_date} 的数据字段缺失: missing={missing_columns}。")
                return None

            column_map = {
                "nav": "单位净值"
            }
            hist_metric_data_list = self._build_hist_data_list(raw_df, symbol, column_map, date_field_name="净值日期")
            logger.info(f"成功获取{symbol} {start_date} 至 {end_date} 的净值数据，记录数为{len(hist_metric_data_list)}。")
            return pd.DataFrame(hist_metric_data_list)
        # 网络异常向上传播，由 @retry_on_error 装饰器处理重试
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"数据解析错误 symbol={symbol}，开始时间为{start_date}，结束时间为{end_date}，错误信息：{e}。")
            return None
    
    @rate_limit(min_interval=6.0, key="baostock")
    @retry_on_error(max_retries=3, retry_delay=8.0)
    def get_etf_daily_from_baostock(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        fields: str = "date, code, open, high, low, close, volume, amount, turn, tradestatus"
    ) -> Optional[pd.DataFrame]:
        """从 BaoStock 提供的接口获取指定 ETF 的指标数据。

        Args:
            symbol: ETF 代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
            fields: 指标字段，默认包含 OHLCV 等核心字段

        Returns:
            包含 trade_date/symbol/open_px/high_px/low_px/close_px 等列的 DataFrame，
            无数据时返回 None

        Example:
            >>> fetcher = DailyFetcher()
            >>> df = fetcher.get_etf_daily_from_baostock("159227", "2026-04-01", "2026-04-28")
            >>> print("open_px" in df.columns)
            True
        """
        lg = bs.login()
        if lg.error_code != self.GOOD_STATUS_CODE:
            logger.error(f"登录 BaoStock 失败， 错误码: {lg.error_code}, 错误信息: {lg.error_msg}")
            return None

        # 根据ETF编码开头数字判断市场，目前只支持A股市场
        market_label = "sz" if symbol.startswith("1") else "sh"

        bs_raw_data = bs.query_history_k_data_plus(
            code=f"{market_label}.{symbol}",
            fields=fields,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 默认前复权
        )

        if bs_raw_data.error_code != self.GOOD_STATUS_CODE:
            logger.error(f"查询 BaoStock 失败， 错误码: {bs_raw_data.error_code}, 错误信息: {bs_raw_data.error_msg}")
            return None

        data_list = []
        while (bs_raw_data.error_code == self.GOOD_STATUS_CODE) and bs_raw_data.next():
            row_data = bs_raw_data.get_row_data()
            data = {
                "trade_date": row_data[0],
                "symbol": symbol,
                "open_px": float(row_data[2]),
                "high_px": float(row_data[3]),
                "low_px": float(row_data[4]),
                "close_px": float(row_data[5]),
                "volume": int(float(row_data[6]) / 100),  # baostock提供的单位是股，转换为手
                "amount": float(row_data[7]),
                "turnover_rate": float(row_data[8]) if row_data[8] != "" else 0.0,
                "trade_status": int(row_data[9])
            }
            data_list.append(data)
        logger.info(f"成功获取{symbol} {start_date} 至 {end_date} 的日线数据，记录数为{len(data_list)}。")
        bs.logout()
        return pd.DataFrame(data_list)

    def fetch_daily(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """拉取 OHLCV + NAV 并合并为统一格式。

        BaoStock 提供日线行情（OHLCV），东方财富补充单位净值（NAV），
        按 trade_date + symbol 做左连接，NAV 缺失时对应列为 None。

        Args:
            symbol: ETF 代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            列包含 code/date/open/high/low/close/volume/nav/premium_rate 的 DataFrame

        Example:
            >>> fetcher = DailyFetcher()
            >>> df = fetcher.fetch_daily("159227", "2026-04-01", "2026-04-28")
            >>> print(df.columns.tolist())
            ['code', 'date', 'open', 'high', 'low', 'close', 'volume', 'nav', 'premium_rate']
        """
        ohlcv_df = self.get_etf_daily_from_baostock(symbol, start_date, end_date)
        if ohlcv_df is None or ohlcv_df.empty:
            logger.warning(f"BaoStock 未返回 {symbol} 在 {start_date}~{end_date} 的数据")
            return pd.DataFrame()

        # 东方财富日期格式为 YYYYMMDD
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")
        nav_df = self.get_etf_metric_from_eastmoney(symbol, start_fmt, end_fmt)

        if nav_df is not None and not nav_df.empty:
            # 统一 trade_date 为 str，防止上游 dtype 不一致导致 merge 静默失败
            ohlcv_df["trade_date"] = ohlcv_df["trade_date"].astype(str)
            nav_df["trade_date"] = nav_df["trade_date"].astype(str)
            merged = ohlcv_df.merge(nav_df, on=["trade_date", "symbol"], how="left")
            # 归一化 NAV：空字符串/非法值 → NaN，避免下游出现三种状态
            merged["nav"] = pd.to_numeric(merged["nav"], errors="coerce")
        else:
            merged = ohlcv_df
            merged["nav"] = None

        # 统一列名与模型对齐
        merged = merged.rename(columns={
            "trade_date": "date",
            "symbol": "code",
            "open_px": "open",
            "high_px": "high",
            "low_px": "low",
            "close_px": "close",
        })

        # 计算溢价率
        merged["premium_rate"] = merged.apply(
            lambda r: (r["close"] - r["nav"]) / r["nav"]
            if pd.notna(r["nav"]) and r["nav"] != 0
            else None,
            axis=1,
        )

        return merged[["code", "date", "open", "high", "low",
                        "close", "volume", "nav", "premium_rate"]]


if __name__ == "__main__":
    fetcher = DailyFetcher()
    df = fetcher.get_etf_daily_from_baostock("515050", "2026-05-01", "2026-05-14")
    # df = fetcher.get_etf_metric_from_eastmoney("513100", "20260513", "20260514")
    # df = fetcher.fetch_daily("513100", "2026-05-12", "2026-05-14")
    print(df)
