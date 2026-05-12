"""系统初始化：建表 → 回填行情 → 计算指标 → 生成信号。

首次初始化: python main.py init
增量回填:   python main.py init --symbol 588000 --start 2024-01-01
"""

from datetime import date, timedelta

from src.config import load_config
from src.database import init_engine, dispose_engine, indicators_repo, signals_repo
from src.database.schema import Base
from src.fetcher import DailyFetcher, DataManager
from src.indicators import MASystem, MACD, Bollinger, VolumeIndicator, RSI
from src.runner.daily_runner import _indicators_to_dataframe
from src.service import TradingCalendarService, IndicatorService
from src.strategy import create_strategy
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
    logger.info("表创建完成")

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

    # 2. 回填行情
    logger.info(f"回填 {start_date} ~ {t_minus_1} 行情数据...")
    fetcher = DailyFetcher()
    dm = DataManager(config, fetcher, calendar)
    for etf in targets:
        dm.backfill(symbol=etf.symbol, start_date=start_date)

    # 3. 回填指标
    logger.info(f"回填 {start_date} ~ {t_minus_1} 技术指标...")
    service = IndicatorService()
    service.register(MASystem(
        ma_short=config.strategy_params.get("ma_short", 20),
        ma_long=config.strategy_params.get("ma_long", 60),
    ))
    service.register(MACD())
    service.register(Bollinger(window=20, num_std=2.0))
    service.register(VolumeIndicator(window=20))
    service.register(RSI(period=14))
    for etf in targets:
        n = service.calculate_and_save(etf.symbol, start_date, t_minus_1)
        logger.info(f"指标: {etf.symbol} 写入 {n} 条")

    # 4. 生成信号
    logger.info(f"生成 {start_date} ~ {t_minus_1} 交易信号...")
    strategy = create_strategy(config)
    for etf in targets:
        indicators = indicators_repo.find_by_code_between(
            etf.symbol, start_date, t_minus_1
        )
        if not indicators:
            logger.warning(f"信号: {etf.symbol} 无指标数据，跳过")
            continue

        df = _indicators_to_dataframe(indicators)
        signal_df = strategy.generate(df)

        saved = 0
        for _, row in signal_df.iterrows():
            if row["signal"] == "HOLD" and (
                "unknown" in str(row.get("signal_meta", {}).get("trend", ""))
            ):
                continue
            signals_repo.save(
                code=etf.symbol,
                date=date.fromisoformat(row["date"]) if isinstance(row["date"], str) else row["date"],
                signal=row["signal"],
                version=row["strategy_version"],
                meta=row["signal_meta"],
            )
            saved += 1
        logger.info(f"信号: {etf.symbol} 写入 {saved} 条")

    dispose_engine()
    logger.info("系统初始化完成")


if __name__ == "__main__":
    init_system()
