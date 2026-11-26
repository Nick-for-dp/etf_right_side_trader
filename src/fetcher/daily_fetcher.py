import akshare as ak
import baostock as bs
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict, Any

from .base import BaseFetcher
from .baostock_session import BaoStockUnavailable, baostock_session
from src.utils import get_logger, rate_limit, retry_on_error


logger = get_logger(__name__)


class DailyFetcher(BaseFetcher):
    """通过 BaoStock（日常）与东方财富（历史回填）拉取 ETF 日线 OHLCV + NAV。

    OHLCV（日常）: BaoStock — 稳定，近 6 个月数据
    OHLCV（历史）: ak.fund_etf_hist_em — 东方财富，支持上市以来全量历史，反爬严格
    NAV:          ak.fund_etf_fund_info_em — 东方财富，单位净值
    """

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
    
    @rate_limit(min_interval=6.0, key="baostock")
    @retry_on_error(max_retries=3, retry_delay=8.0)
    def get_etf_daily_from_baostock(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        fields: str = "date, code, open, high, low, close, volume, amount, turn, tradestatus"
    ) -> Optional[pd.DataFrame]:
        """从 BaoStock 获取指定 ETF 的日线 OHLCV 数据（前复权）。

        BaoStock 稳定可靠，适合日常增量同步，但仅覆盖近 ~6 个月数据。

        Args:
            symbol: ETF 代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
            fields: 指标字段，默认包含 OHLCV 等核心字段

        Returns:
            包含 trade_date/symbol/open_px/high_px/low_px/close_px/volume 等列的 DataFrame，
            无数据时返回 None
        """
        try:
            with baostock_session():
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
                    raise BaoStockUnavailable(
                        f"查询失败: {bs_raw_data.error_code} {bs_raw_data.error_msg}"
                    )

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
        except BaoStockUnavailable as exc:
            logger.warning(f"BaoStock 不可用，{symbol} 将使用东方财富兜底: {exc}")
            return None

        logger.info(f"成功获取{symbol} {start_date} 至 {end_date} 的日线数据（BaoStock），"
                    f"记录数为{len(data_list)}。")
        return pd.DataFrame(data_list)

    @rate_limit(min_interval=60.0, key="eastmoney_ohlcv")
    @retry_on_error(max_retries=3, retry_delay=15.0)
    def get_etf_daily_from_eastmoney(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """从东方财富获取 ETF 日线 OHLCV 数据（前复权）。

        作为 BaoStock 的历史数据补充，支持从 ETF 上市日起的全量历史数据，
        满足长期赔率因子对 3 年以上窗口的需求。反爬机制严格，仅用于回填场景。

        Args:
            symbol: ETF 代码
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"

        Returns:
            包含 trade_date/symbol/open_px/high_px/low_px/close_px/volume 等列的 DataFrame，
            无数据时返回 None

        Example:
            >>> fetcher = DailyFetcher()
            >>> df = fetcher.get_etf_daily_from_eastmoney("588000", "20201116", "20260514")
            >>> print("open_px" in df.columns)
            True
        """
        if not end_date:
            end_date = datetime.today().strftime("%Y%m%d")

        try:
            raw_df = ak.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )

            if raw_df.empty:
                logger.warning(f"东方财富未返回 {symbol} 在 {start_date}~{end_date} 的数据")
                return None

            # 东方财富返回中文列名 → 英文列名
            column_map = {
                "open_px": "开盘",
                "high_px": "最高",
                "low_px": "最低",
                "close_px": "收盘",
                "volume": "成交量",
                "amount": "成交额",
                "turnover_rate": "换手率",
            }
            hist_list = self._build_hist_data_list(raw_df, symbol, column_map, date_field_name="日期")
            logger.info(f"成功获取{symbol} {start_date} 至 {end_date} 的日线数据（东方财富），"
                        f"记录数为{len(hist_list)}。")
            return pd.DataFrame(hist_list)
        # 网络异常向上传播，由 @retry_on_error 装饰器处理重试
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"数据解析错误 symbol={symbol}，开始时间为{start_date}，"
                         f"结束时间为{end_date}，错误信息：{e}。")
            return None

    def fetch_daily(self, symbol: str, start_date: str, end_date: str,
                     skip_baostock: bool = False) -> pd.DataFrame:
        """拉取 OHLCV + NAV 并合并为统一格式。

        OHLCV 优先使用 BaoStock（稳定，适合日常增量），BaoStock 无数据时
        回退到东方财富 fund_etf_hist_em（支持全量历史，但反爬严格）。
        skip_baostock=True 时跳过 BaoStock，直接走东方财富（历史回填场景）。

        Args:
            symbol: ETF 代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
            skip_baostock: True 时跳过 BaoStock，直接使用东方财富

        Returns:
            列包含 code/date/open/high/low/close/volume 的 DataFrame
        """
        # 东方财富日期格式为 YYYYMMDD
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")

        if skip_baostock:
            ohlcv_df = self.get_etf_daily_from_eastmoney(symbol, start_fmt, end_fmt)
        else:
            # 日常增量优先走 BaoStock（稳定），无数据时回退东方财富（历史数据）
            ohlcv_df = self.get_etf_daily_from_baostock(symbol, start_date, end_date)
            if ohlcv_df is None or ohlcv_df.empty:
                logger.info(f"BaoStock 无 {symbol} 在 {start_date}~{end_date} 的数据，"
                            f"回退东方财富。")
                ohlcv_df = self.get_etf_daily_from_eastmoney(symbol, start_fmt, end_fmt)

        if ohlcv_df is None or ohlcv_df.empty:
            logger.warning(f"{symbol} 在 {start_date}~{end_date} 无数据")
            return pd.DataFrame()

        # 统一列名与模型对齐
        merged = ohlcv_df.rename(columns={
            "trade_date": "date",
            "symbol": "code",
            "open_px": "open",
            "high_px": "high",
            "low_px": "low",
            "close_px": "close",
        })

        return merged[["code", "date", "open", "high", "low", "close", "volume"]]


if __name__ == "__main__":
    fetcher = DailyFetcher()
    # 测试 BaoStock（日常增量）
    df = fetcher.get_etf_daily_from_baostock("588000", "2026-05-01", "2026-05-14")
    print("BaoStock:", df.shape if df is not None else "None")
    # 测试东方财富（历史回填）
    df2 = fetcher.get_etf_daily_from_eastmoney("588000", "20201116", "20260514")
    print("EastMoney:", df2.shape if df2 is not None else "None")
