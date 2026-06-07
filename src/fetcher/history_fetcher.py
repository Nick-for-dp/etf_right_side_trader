import os
import tushare as ts
import pandas as pd
from dotenv import load_dotenv
from typing import Optional

from src.utils import get_logger, rate_limit


load_dotenv()
logger = get_logger(__name__)


class HistoryFetcher:
    """Tushare 历史行情数据拉取器。

    作为现有 BaoStock + AKShare 链路的补充：Tushare API 稳定性高，适合一次性拉取
    ETF 和宽基指数的历史日线。

    单位转换：
    - ETF volume: Tushare fund_daily 原始单位是"手"，保持不变，与 Quote 链路一致。
    - 指数 volume: Tushare index_daily 原始单位是"手"，转换为"股"（×100），
      与 BaoStock / AKShare 指数日常链路一致。
    - amount: Tushare 原始单位是"千元"，统一转为"元"（×1000）。
    """

    def __init__(self):
        token = os.getenv("TUSHARE_TOKEN")
        if not token:
            raise ValueError("环境变量 TUSHARE_TOKEN 未设置，无法初始化 Tushare API。")
        self.pro = ts.pro_api(token)
        # 自定义 API 网关地址（如私有化部署），为空则使用 Tushare 默认云端
        tushare_url = os.getenv("TUSHARE_URL")
        if tushare_url:
            self.pro._DataApi__http_url = tushare_url
            logger.info("Tushare API 端点已设置为自定义地址")

    @staticmethod
    def _index_to_ts_code(symbol: str, tushare_code: str = "") -> str:
        """将指数代码转换为 Tushare ts_code 格式。

        支持中证行业指数（93xxxx/98xxxx/Hxxxxx → .CI）、
        港股指数（HZxxxx → .HI）、
        深证指数（399xxx → .SZ）和上证指数（其他 → .SH）。
        显式传入 tushare_code 时直接返回。

        Args:
            symbol: 6 位指数代码或完整代码
            tushare_code: 显式指定的 Tushare ts_code（为空时自动推导）

        Returns:
            完整的 Tushare ts_code，如 "000300.SH" / "399967.SZ" / "931151.CI"
        """
        if tushare_code:
            return tushare_code

        symbol = symbol.strip()
        # 港股指数：HZxxxx → .HI
        if symbol.startswith("HZ"):
            return f"{symbol}.HI"
        # CSI 中证指数：93xxx/98xxx/Hxxxx → .CI
        if symbol.startswith(("93", "98", "99")) or symbol.startswith("H"):
            return f"{symbol}.CI"
        # 深证指数
        if symbol.startswith("399"):
            return f"{symbol}.SZ"
        # 默认上证
        return f"{symbol}.SH"

    def get_index_history_from_tushare(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        tushare_code: str = "",
    ) -> Optional[pd.DataFrame]:
        """从 Tushare 获取宽基指数历史日线行情。

        Tushare 的 index_daily 接口返回宽基指数 OHLCV 和成交额。返回结果会
        转换为 market_index_quote 表对应字段，可直接构造 MarketIndexQuote。

        Args:
            symbol: 宽基指数代码（6 位数字，如 "000300"）
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"
            tushare_code: 显式指定 Tushare ts_code，为空时自动推导

        Returns:
            包含以下列的 DataFrame，无数据时返回 None：
            - index_code:     宽基指数代码
            - date:           交易日期
            - open/high/low/close: OHLC
            - volume:         成交量（股），与 BaoStock / AKShare 指数日常链路一致
            - amount:         成交额（元）

        Example:
            >>> fetcher = HistoryFetcher()
            >>> df = fetcher.get_index_history_from_tushare("000300", "20200101", "20201231")
            >>> print(df.columns.tolist())
            ['index_code', 'date', 'open', 'high', 'low', 'close', 'volume', 'amount']
        """
        # ── step 1: 补全交易所后缀，转换为 Tushare ts_code 格式 ──
        symbol = symbol.strip()
        if len(symbol) != 6 and not tushare_code:
            raise ValueError(f"指数代码长度必须为 6 位，输入代码 {symbol} 不符合要求。")
        ts_code = self._index_to_ts_code(symbol, tushare_code)

        # ── step 2: 拉取宽基指数日线行情 ──
        # Tushare index_daily 字段名：vol（成交量，手）、amount（成交额，千元）
        price_df = self.pro.index_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="trade_date,open,high,low,close,vol,amount",
        )
        if price_df.empty:
            logger.info(f"指数 {ts_code} 在 {start_date} ~ {end_date} 之间无行情数据。")
            return None

        df = price_df.rename(columns={"trade_date": "date", "vol": "volume"})
        df = df.sort_values("date").reset_index(drop=True)

        # index_daily: volume 为手，amount 为千元；转为日常指数链路使用的股/元口径。
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce") * 100
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1000
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
        df["index_code"] = symbol

        logger.info(
            f"成功获取 {symbol} {start_date} ~ {end_date} 的指数历史行情 "
            f"（Tushare），共 {len(df)} 条记录。"
        )

        return df[["index_code", "date", "open", "high", "low", "close",
                   "volume", "amount"]]

    @rate_limit(min_interval=2.0, key="tushare")
    def get_global_index_history_from_tushare(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        tushare_code: str = "",
    ) -> Optional[pd.DataFrame]:
        """从 Tushare 获取全球指数历史日线行情。

        适用于恒生科技指数等不在 index_daily 中的数据。Tushare 的
        index_global 接口返回 OHLC，部分指数 volume 为空，成交额不可用。

        Args:
            symbol: 系统内部指数代码，如 "HZ5017"
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"
            tushare_code: Tushare 全球指数代码，如 "HKTECH"

        Returns:
            包含 market_index_quote 可直接消费字段的 DataFrame，无数据时返回 None。
        """
        symbol = symbol.strip()
        ts_code = (tushare_code or symbol).strip()
        if not ts_code:
            raise ValueError(f"全球指数 {symbol} 未配置 Tushare ts_code。")

        price_df = self.pro.index_global(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )
        if price_df is None or price_df.empty:
            logger.info(f"全球指数 {ts_code} 在 {start_date} ~ {end_date} 之间无行情数据。")
            return None

        df = price_df.rename(columns={"trade_date": "date", "vol": "volume"})
        df = df.sort_values("date").reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = None
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
        df["index_code"] = symbol
        df["amount"] = None

        logger.info(
            f"成功获取 {symbol}/{ts_code} {start_date} ~ {end_date} 的全球指数历史行情 "
            f"（Tushare），共 {len(df)} 条记录。"
        )

        return df[["index_code", "date", "open", "high", "low", "close",
                   "volume", "amount"]]

    @rate_limit(min_interval=2.0, key="tushare")
    def get_etf_history_from_tushare(
        self,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """从 Tushare 获取 ETF 历史日线行情，手动计算前复权价格。

        Tushare 的 fund_daily 接口返回不复权数据，需配合 fund_adj 复权因子
        手动计算前复权 OHLC。建议按年为单位分批拉取，避免单次数据量过大。

        Args:
            symbol: ETF 代码（6 位数字，如 "510050"）
            start_date: 开始日期，格式 "YYYYMMDD"
            end_date: 结束日期，格式 "YYYYMMDD"

        Returns:
            包含以下列的 DataFrame，无数据时返回 None：
            - code:           ETF 代码
            - date:           交易日期
            - open/high/low/close: 前复权 OHLC
            - volume:         成交量（手）
            - nav:            单位净值（Tushare 不支持，恒为 None）
            - premium_rate:   溢价率（Tushare 不支持，恒为 None）

        Example:
            >>> fetcher = HistoryFetcher()
            >>> df = fetcher.get_etf_history_from_tushare("510050", "20200101", "20241231")
            >>> print(df.columns.tolist())
            ['code', 'date', 'open', 'high', 'low', 'close', 'volume', 'nav', 'premium_rate']
        """

        # ── step 1: 补全交易所后缀，转换为 Tushare ts_code 格式 ──
        if len(symbol) != 6:
            raise ValueError(f"ETF 代码长度必须为 6 位，输入代码 {symbol} 不符合要求。")
        if symbol.startswith("15"):
            ts_code = f"{symbol}.SZ"
        else:
            ts_code = f"{symbol}.SH"

        # ── step 2: 拉取不复权日线行情 ──
        # Tushare fund_daily 字段名：vol（成交量，手）、amount（成交额，千元）
        price_df = self.pro.fund_daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="trade_date,open,close,high,low,vol,amount"
        )
        if price_df.empty:
            logger.info(f"ETF {ts_code} 在 {start_date} ~ {end_date} 之间无行情数据。")
            return None
        # 统一列名：vol → volume，与下游 Quote 模型字段对齐
        price_df = price_df.rename(columns={"vol": "volume"})

        # ── step 3: 拉取复权因子 ──
        adj_factor_df = self.pro.fund_adj(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )
        # 部分 ETF 从未发生分红/拆分，fund_adj 返回空表，此时 adj_factor 全部视为 1.0
        if adj_factor_df.empty:
            logger.warning(
                f"ETF {ts_code} 无复权因子数据（可能从未分红/拆分），"
                f"所有交易日的 adj_factor 均设为 1.0。"
            )
            price_df["adj_factor"] = 1.0
            df = price_df
        else:
            # left join：以行情数据为左表，确保不丢行情行
            df = pd.merge(price_df, adj_factor_df, on="trade_date", how="left")
            # 新上市 ETF 的 fund_adj 覆盖范围可能小于 fund_daily，
            # 缺失的 adj_factor 用前向填充兜底，剩余 NaN 补 1.0（上市首日之前）
            df["adj_factor"] = df["adj_factor"].ffill().fillna(1.0)

        # ── step 4: 按 trade_date 升序排列，确保 iloc[-1] 取到最新复权因子 ──
        df = df.sort_values("trade_date").reset_index(drop=True)

        # ── step 5: 前复权计算 ──
        # 前复权公式：前复权价格 = 原始价格 × 当日复权因子 / 最新复权因子
        # 最新复权因子 = 数据集中最后一个交易日的因子值
        latest_factor = df["adj_factor"].iloc[-1]
        for col in ["open", "close", "high", "low"]:
            df[col] = df[col] * df["adj_factor"] / latest_factor

        # ── step 6: 单位转换，对齐 DailyFetcher 的输出格式 ──
        # amount: Tushare 返回千元 → 转为元（×1000），与 BaoStock / 东方财富对齐
        df["amount"] = df["amount"] * 1000

        # ── step 7: 统一列名，对齐 Quote 模型字段 ──
        df = df.rename(columns={"trade_date": "date"})
        # Tushare 返回 YYYYMMDD 字符串（如 "20201116"），Pydantic date 字段无法直接解析，
        # 转为 Python date 对象，Quote(**row) 时无需额外转换
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
        df["code"] = symbol           # 还原为 6 位代码
        df["nav"] = None              # Tushare 不提供完整的净值，后续可从其他源补
        df["premium_rate"] = None     # 无 nav 则无法计算溢价率

        logger.info(
            f"成功获取 {symbol} {start_date} ~ {end_date} 的历史行情 "
            f"（Tushare，前复权），共 {len(df)} 条记录。"
        )

        return df[["code", "date", "open", "high", "low", "close",
                    "volume", "nav", "premium_rate"]]
