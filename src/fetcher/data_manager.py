"""编排数据抓取流程：查缺失 → 拉取 → 写入 quote 表。"""

from datetime import date, timedelta

from src.config import AppConfig
from src.database import quote_repo
from .base import BaseFetcher
from src.models import Quote
from src.service import TradingCalendarService
from src.utils import get_logger

logger = get_logger(__name__)


class DataManager:
    """ETF 列表的日线数据同步协调器。"""

    def __init__(
        self,
        config: AppConfig,
        fetcher: BaseFetcher,
        calendar: TradingCalendarService
    ):
        """初始化数据管理器。

        Args:
            config: 应用配置
            fetcher: 数据抓取器
            calendar: 交易日历服务
        """
        self.config = config
        self.fetcher = fetcher
        self.calendar = calendar

    # ── 公开方法 ──

    def sync_daily(self) -> None:
        """每日增量同步：将所有 ETF 补齐到 T-1 交易日。

        已有数据则只拉增量；首次运行（无历史数据）自动回退全量拉取。

        Returns:
            None
        """
        t_minus_1 = self.calendar.get_previous_trading_day()
        t_minus_1_date = date.fromisoformat(t_minus_1)

        for etf in self.config.etf_list:
            latest = quote_repo.find_latest_date(etf.symbol)

            if latest and latest >= t_minus_1_date:
                continue

            if latest:
                start_date = latest + timedelta(days=1)
            else:
                start_date = t_minus_1_date - timedelta(days=self.config.lookback_days)

            n = self._fetch_and_save(etf.symbol, start_date.isoformat(), t_minus_1)
            logger.info(f"sync_daily: {etf.symbol} 写入 {n} 条, "
                        f"{start_date.isoformat()} ~ {t_minus_1}")

    def backfill(self, symbol: str | None = None,
                 start_date: date | None = None) -> None:
        """回填历史数据，覆盖 [start_date, T-1] 区间内所有缺失日期。

        支持双向补全：
        - 向前补（start_date ~ 最早记录-1）：已有数据较早但需扩展历史
        - 向后补（最新记录+1 ~ T-1）：增量追平最新交易日

        Args:
            symbol: 指定 ETF 代码，为 None 时回填配置中所有 ETF
            start_date: 自定义起始日期，为 None 时按 lookback_days 推算

        Returns:
            None
        """
        t_minus_1 = self.calendar.get_previous_trading_day()
        t_minus_1_date = date.fromisoformat(t_minus_1)

        if start_date is None:
            start_date = t_minus_1_date - timedelta(days=self.config.lookback_days)

        targets = [symbol] if symbol else [e.symbol for e in self.config.etf_list]
        for s in targets:
            # 查询 DB 中已有数据的日期范围
            latest = quote_repo.find_latest_date(s)
            earliest = quote_repo.find_earliest_date(s)

            # 向前补：已由 Tushare backfill-tushare 覆盖全量历史日线，不再走东方财富
            # 仅检测缺口并提示用户使用 backfill-tushare 命令
            if earliest is not None and start_date < earliest:
                logger.warning(
                    f"backfill: {s} 历史数据缺口 ({start_date.isoformat()} < "
                    f"{earliest.isoformat()})，请执行 backfill-tushare 补全"
                )

            # 向后补：追平最新交易日（latest+1 到 T-1 之间的缺口）
            if latest is None:
                forward_start = None
            elif latest < t_minus_1_date:
                forward_start = latest + timedelta(days=1)
            else:
                forward_start = None

            if forward_start is not None:
                n = self._fetch_and_save(s, forward_start.isoformat(),
                                         t_minus_1)
                logger.info(f"backfill(后): {s} 写入 {n} 条, "
                            f"{forward_start.isoformat()} ~ {t_minus_1}")

            if forward_start is None:
                logger.info(f"backfill: {s} 数据已完整 "
                            f"({earliest.isoformat() if earliest else 'N/A'} ~ "
                            f"{latest.isoformat() if latest else 'N/A'})，跳过")

    # ── Tushare 历史回填（临时方案，token 过期前使用） ──

    def backfill_tushare(
        self,
        symbol: str | None = None,
        start_date: str = "20200101",
        end_date: str | None = None,
    ) -> None:
        """使用 Tushare 批量回填 ETF 历史 OHLCV（临时方案）。

        Tushare API 稳定性高但不提供 NAV，适合用于补充长期历史日线。
        通过 save_batch 的 ON CONFLICT DO NOTHING 保证已有数据（含 NAV）
        不被覆盖，仅填补缺失日期的 OHLCV 数据。

        注意：此方法不拉 NAV，执行后需用东方财富数据源补净值。

        Args:
            symbol: 单只 ETF 代码（6 位数字），None = 覆盖 settings.yaml 中全部 ETF
            start_date: 起始日期 YYYYMMDD，默认 20180101（Tushare 数据最早约到 2018 年）
            end_date: 截止日期 YYYYMMDD，None = T-1 上一个交易日
        """
        from .history_fetcher import HistoryFetcher

        if end_date is None:
            end_date = self.calendar.get_previous_trading_day().replace("-", "")

        targets = [symbol] if symbol else [e.symbol for e in self.config.etf_list]

        fetcher = HistoryFetcher()

        for s in targets:
            # 查询 DB 中已有数据的日期范围，用于日志对比
            db_earliest = quote_repo.find_earliest_date(s)
            db_latest = quote_repo.find_latest_date(s)

            # 从 Tushare 拉取全量历史 OHLCV（含前复权处理）
            df = fetcher.get_etf_history_from_tushare(s, start_date, end_date)
            if df is None or df.empty:
                logger.warning(f"Tushare backfill: {s} 无数据，跳过")
                continue

            # save_batch 使用 ON CONFLICT DO NOTHING，
            # 已存在的 (code, date) 会被自动跳过，已有 NAV 不被覆盖
            quotes = [Quote(**row) for _, row in df.iterrows()]
            quote_repo.save_batch(quotes)

            # 统计实际写入数
            new_earliest = quote_repo.find_earliest_date(s)
            new_latest = quote_repo.find_latest_date(s)
            logger.info(
                f"Tushare backfill: {s} "
                f"({db_earliest}~{db_latest} → {new_earliest}~{new_latest}) "
                f"共拉取 {len(df)} 条，新增约 {len(df)} 条（重复自动跳过）"
            )

    # ── 内部 ──

    def _fetch_and_save(self, symbol: str, start: str, end: str,
                         skip_baostock: bool = False) -> int:
        """拉取单只 ETF 并写入 quote 表，返回写入条数。

        Args:
            symbol: ETF 代码
            start: 起始日期（YYYY-MM-DD）
            end: 截止日期（YYYY-MM-DD）
            skip_baostock: True 时跳过 BaoStock，直接走东方财富
        """
        df = self.fetcher.fetch_daily(symbol, start, end,
                                       skip_baostock=skip_baostock)
        if df.empty:
            return 0
        quotes = [Quote(**row) for _, row in df.iterrows()]
        quote_repo.save_batch(quotes)
        return len(quotes)
