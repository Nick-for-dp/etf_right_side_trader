"""系统初始化：建表 → 回填 ETF/指数行情 → 计算市场状态/指标 → 生成信号。

首次初始化:       python main.py init
单 ETF 增量回填:  python main.py init --symbol 588000 --start 2024-01-01
市场状态初始化:   python main.py init-market --start 2022-01-01
"""

from datetime import date, timedelta

from src.config import load_config
from src.database import (
    init_engine,
    dispose_engine,
    market_index_quote_repo,
    signals_repo,
)
from src.database.schema import Base
from src.database.schema_maintenance import ensure_schema
from src.fetcher import DailyFetcher, DataManager, HistoryFetcher
from src.models import MarketIndexQuote
from src.service import (
    TradingCalendarService,
    MarketRegimeService,
    EtfMappingService,
)
from src.service.indicator_service import build_indicator_service
from src.utils import get_logger

logger = get_logger(__name__)


def init_system(symbol: str | None = None,
                start_date: date | None = None) -> None:
    """建表并回填数据。

    支持全量初始化（无参数）和单只 ETF 增量初始化（--symbol + --start）。
    已有数据自动跳过，避免重复拉取。

    Args:
        symbol: 单只 ETF 代码，None 时覆盖配置中全部 ETF
        start_date: 回填起始日期，None 时按 lookback_days 推算
    """
    config = load_config()
    engine = init_engine(config.db_url)

    # 1. 建表
    logger.info("创建数据库表...")
    Base.metadata.create_all(engine)
    ensure_schema(engine)
    logger.info("表创建完成")
    result = EtfMappingService.sync_from_config(config)
    logger.info(
        "ETF 映射同步完成: "
        f"config={result.total_config} saved={result.saved} "
        f"deleted_stale={result.deleted_stale}"
    )

    calendar = TradingCalendarService()
    t_minus_1_str = calendar.get_previous_trading_day()
    t_minus_1 = date.fromisoformat(t_minus_1_str)

    if start_date is None:
        start_date = t_minus_1 - timedelta(days=config.lookback_days)

    # 确定目标 ETF 列表
    if symbol:
        targets = [e for e in config.etf_list if e.symbol == symbol]
        if not targets:
            raise ValueError(f"ETF {symbol} 不在 settings.yaml 的 etf_list 中")
    else:
        targets = config.etf_list

    # 2. 回填 ETF 行情
    logger.info(f"回填 {start_date} ~ {t_minus_1} ETF 行情数据...")
    fetcher = DailyFetcher()
    dm = DataManager(config, fetcher, calendar)
    for etf in targets:
        dm.backfill(symbol=etf.symbol, start_date=start_date)

    # 3. 回填宽基指数历史行情（Tushare）
    _backfill_market_indices(config, start_date, t_minus_1)

    # 4. 计算市场热度历史
    _calculate_market_regime_history(config, calendar, start_date, t_minus_1)

    # 5. 回填指标
    logger.info(f"回填 {start_date} ~ {t_minus_1} 技术指标...")
    service = build_indicator_service(config)
    for etf in targets:
        n = service.calculate_and_save(etf.symbol, start_date, t_minus_1)
        logger.info(f"指标: {etf.symbol} 写入 {n} 条")

    # 6. 生成信号（与每日流程、rebuild-signals 同一实现）
    logger.info(f"生成 {start_date} ~ {t_minus_1} 交易信号...")
    from src.service.signal_rebuild_service import generate_code_signals
    from src.strategy import create_strategy

    strategy = create_strategy(config)
    for etf in targets:
        records, stats = generate_code_signals(etf.symbol, start_date, t_minus_1, strategy)
        if records:
            signals_repo.save_batch(records)
        logger.info(f"信号: {etf.symbol} 写入 {len(records)} 条 {stats.warning}".strip())

    dispose_engine()
    logger.info("系统初始化完成")


def init_market_data(start_date: date | None = None,
                     end_date: date | None = None) -> None:
    """初始化宽基指数历史行情和市场热度快照。

    用于 ETF 行情、指标和信号已经完成初始化的环境，只补齐市场热度门控
    所需的 market_index_quote 与 market_regime。

    Args:
        start_date: 回填起始日期，None 时按 data.lookback_days 推算
        end_date: 回填截止日期，None 时使用 T-1 上一个交易日
    """
    config = load_config()
    engine = init_engine(config.db_url)

    logger.info("创建数据库表...")
    Base.metadata.create_all(engine)
    ensure_schema(engine)
    logger.info("表创建完成")
    result = EtfMappingService.sync_from_config(config)
    logger.info(
        "ETF 映射同步完成: "
        f"config={result.total_config} saved={result.saved} "
        f"deleted_stale={result.deleted_stale}"
    )

    calendar = TradingCalendarService()
    if end_date is None:
        t_minus_1_str = calendar.get_previous_trading_day()
        end_date = date.fromisoformat(t_minus_1_str)

    if start_date is None:
        start_date = end_date - timedelta(days=config.lookback_days)

    _backfill_market_indices(config, start_date, end_date)
    _calculate_market_regime_history(config, calendar, start_date, end_date)

    dispose_engine()
    logger.info("市场状态初始化完成")


def _backfill_market_indices(config, start_date: date, end_date: date) -> None:
    """回填宽基与全球指数历史日线。

    优先使用 Tushare（覆盖 A 股宽基）。
    Tushare 不覆盖或失败时，回退到 MarketIndexFetcher（按 index.source 分发）。
    美股指数（akshare_us）不走 Tushare，直接走 AKShare。
    """
    if not config.market_indices:
        logger.info("未配置 market.indices，跳过指数历史回填")
        return

    from src.fetcher.market_index_fetcher import MarketIndexFetcher

    start_fmt = start_date.strftime("%Y%m%d")
    end_fmt = end_date.strftime("%Y%m%d")
    mif = MarketIndexFetcher()

    # 预创建 HistoryFetcher（Tushare 可能 token 无效，捕获异常回退）
    tushare_fetcher = None
    try:
        tushare_fetcher = HistoryFetcher()
    except ValueError as e:
        logger.warning(f"Tushare 初始化失败，将全部走配置源回退: {e}")

    logger.info(f"回填 {start_date} ~ {end_date} 指数历史行情...")
    for index in config.market_indices:
        # 全球指数：如恒生科技 HKTECH，走 Tushare index_global。
        if index.source == "tushare_global":
            if tushare_fetcher is None:
                logger.warning(f"指数历史: {index.code}(全球指数) Tushare 不可用，跳过")
                continue
            try:
                df = tushare_fetcher.get_global_index_history_from_tushare(
                    index.code,
                    start_fmt,
                    end_fmt,
                    tushare_code=index.tushare_code,
                )
                if df is None or df.empty:
                    logger.warning(f"指数历史: {index.code}(全球指数) 无数据，跳过")
                    continue
                records = [MarketIndexQuote(**row) for _, row in df.iterrows()]
                market_index_quote_repo.save_batch(records)
                logger.info(f"指数历史: {index.code}(全球指数) 写入 {len(records)} 条")
            except Exception as exc:
                logger.warning(f"指数历史: {index.code}(全球指数) 异常: {exc}")
            continue

        # 美股指数：不走 Tushare，直接走 AKShare
        if index.source == "akshare_us":
            df = mif.fetch_daily(index, start_date.isoformat(), end_date.isoformat())
            if df.empty:
                logger.warning(f"指数历史: {index.code}(美股) 无数据，跳过")
                continue
            records = [MarketIndexQuote(**row) for _, row in df.iterrows()]
            market_index_quote_repo.save_batch(records)
            logger.info(f"指数历史: {index.code}(美股) 写入 {len(records)} 条")
            continue

        # 优先 Tushare
        tushare_ok = False
        if tushare_fetcher is not None:
            try:
                df = tushare_fetcher.get_index_history_from_tushare(
                    index.code, start_fmt, end_fmt,
                    tushare_code=index.tushare_code,
                )
                if df is not None and not df.empty:
                    records = [MarketIndexQuote(**row) for _, row in df.iterrows()]
                    market_index_quote_repo.save_batch(records)
                    logger.info(f"指数历史: {index.code}(Tushare) 写入 {len(records)} 条")
                    tushare_ok = True
                else:
                    logger.warning(f"指数历史: {index.code} Tushare 无数据")
            except Exception as exc:
                logger.warning(f"指数历史: {index.code} Tushare 异常: {exc}")

        # Tushare 失败或不可用 → 回退到配置源
        if not tushare_ok:
            df = mif.fetch_daily(index, start_date.isoformat(), end_date.isoformat())
            if df.empty:
                logger.warning(f"指数历史: {index.code}(回退) 无数据，跳过")
                continue
            records = [MarketIndexQuote(**row) for _, row in df.iterrows()]
            market_index_quote_repo.save_batch(records)
            logger.info(f"指数历史: {index.code}(回退) 写入 {len(records)} 条")


def _calculate_market_regime_history(config, calendar: TradingCalendarService,
                                     start_date: date, end_date: date) -> None:
    """按交易日批量计算市场状态历史快照（RISK_OFF / NORMAL / UNKNOWN）。"""
    if not config.market_regime_params.get("enabled", True):
        logger.info("市场状态门控未启用，跳过 market_regime 历史计算")
        return

    trading_days = calendar.get_trading_days_in_range(start_date, end_date)
    service = MarketRegimeService(config.market_indices, config.market_regime_params)

    saved = 0
    logger.info(f"计算 {start_date} ~ {end_date} 市场状态历史，共 {len(trading_days)} 个交易日")
    for day_str in trading_days:
        regime = service.calculate_and_save(date.fromisoformat(day_str))
        saved += 1
        if saved % 50 == 0:
            logger.info(
                f"市场状态: 已计算 {saved}/{len(trading_days)}，"
                f"latest={day_str} state={regime.state}"
            )
    logger.info(f"市场状态历史计算完成，写入/更新 {saved} 条")


if __name__ == "__main__":
    init_system()
