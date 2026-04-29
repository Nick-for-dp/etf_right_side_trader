"""系统初始化：建表 → 回填行情 → 计算指标 → 生成信号。

首次运行: python init_db.py
日常运行: python daily_runner.py  或  python run_scheduler.py
"""

from datetime import date, timedelta

from src.config import load_config
from src.database import init_engine, dispose_engine, indicators_repo, signals_repo
from src.database.schema import Base
from src.fetcher import DailyFetcher, DataManager
from src.indicators import MASystem
from src.runner.daily_runner import _indicators_to_dataframe
from src.service import TradingCalendarService, IndicatorService
from src.strategy import create_strategy
from src.utils import get_logger

logger = get_logger(__name__)


def init_system() -> None:
    config = load_config()
    engine = init_engine(config.db_url)

    # 1. 建表
    logger.info("创建数据库表...")
    Base.metadata.create_all(engine)
    logger.info("表创建完成")

    calendar = TradingCalendarService()
    t_minus_1_str = calendar.get_previous_trading_day()
    t_minus_1 = date.fromisoformat(t_minus_1_str)
    start_date = t_minus_1 - timedelta(days=config.lookback_days)

    # 2. 回填行情
    logger.info(f"回填 {start_date} ~ {t_minus_1} 行情数据...")
    fetcher = DailyFetcher()
    dm = DataManager(config, fetcher, calendar)
    dm.backfill()

    # 3. 回填指标（全量区间，含停牌日自动跳过）
    logger.info(f"回填 {start_date} ~ {t_minus_1} 技术指标...")
    service = IndicatorService()
    service.register(MASystem(
        ma_short=config.strategy_params.get("ma_short", 20),
        ma_long=config.strategy_params.get("ma_long", 60),
    ))
    for etf in config.etf_list:
        n = service.calculate_and_save(etf.symbol, start_date, t_minus_1)
        logger.info(f"指标: {etf.symbol} 写入 {n} 条")

    # 4. 生成信号（全量区间）
    logger.info(f"生成 {start_date} ~ {t_minus_1} 交易信号...")
    strategy = create_strategy(config)
    for etf in config.etf_list:
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
            # 跳过无有效 MA 的行（窗口不足导致 NaN）
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
    logger.info("系统初始化完成，可运行 daily_runner.py 或 run_scheduler.py")


if __name__ == "__main__":
    init_system()
