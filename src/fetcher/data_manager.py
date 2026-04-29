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

    def backfill(self, symbol: str | None = None) -> None:
        """全量回填历史数据。

        Args:
            symbol: 指定 ETF 代码，为 None 时回填配置中所有 ETF

        Returns:
            None
        """
        t_minus_1 = self.calendar.get_previous_trading_day()
        t_minus_1_date = date.fromisoformat(t_minus_1)
        start_date = t_minus_1_date - timedelta(days=self.config.lookback_days)

        targets = [symbol] if symbol else [e.symbol for e in self.config.etf_list]
        for s in targets:
            n = self._fetch_and_save(s, start_date.isoformat(), t_minus_1)
            logger.info(f"backfill: {s} 写入 {n} 条, "
                        f"{start_date.isoformat()} ~ {t_minus_1}")

    # ── 内部 ──

    def _fetch_and_save(self, symbol: str, start: str, end: str) -> int:
        """拉取单只 ETF 并写入 quote 表，返回写入条数。"""
        df = self.fetcher.fetch_daily(symbol, start, end)
        if df.empty:
            return 0
        quotes = [Quote(**row) for _, row in df.iterrows()]
        quote_repo.save_batch(quotes)
        return len(quotes)
