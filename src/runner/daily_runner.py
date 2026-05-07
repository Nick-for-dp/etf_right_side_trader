"""串联 STEP 1-5 的核心流程。

可用作：
- 定时调度回调：scheduler 调用 run_daily()
- 手动触发：python daily_runner.py
"""

from datetime import date, timedelta

import pandas as pd

from src.advisor import generate_advice
from src.config import load_config, AppConfig
from src.database import (
    init_engine, dispose_engine,
    indicators_repo, signals_repo, positions_repo, advice_repo, quote_repo,
)
from src.fetcher import DailyFetcher, DataManager
from src.indicators import MASystem, MACD
from src.models import OperationAdvice
from src.risk import RiskController
from src.service import TradingCalendarService, IndicatorService
from src.strategy import create_strategy
from src.utils import get_logger

logger = get_logger(__name__)


def run_daily(target_date: date | None = None) -> None:
    """执行一个交易日的完整流程（STEP 1-5）。

    Args:
        target_date: T 日，默认今天。数据截止 T-1 交易日。

    Returns:
        None

    Example:
        >>> run_daily(date.today())
    """
    config = load_config()
    init_engine(config.db_url)

    calendar = TradingCalendarService()
    t_minus_1_str = calendar.get_previous_trading_day(target_date or date.today())
    t_minus_1 = date.fromisoformat(t_minus_1_str)
    logger.info(f"开始执行 {t_minus_1_str} 的每日流程")

    _step1_sync_data(config, calendar)
    _step2_calc_indicators(config, t_minus_1)
    _step3_generate_signals(config, t_minus_1)
    risk_signals = _step4_risk_check()
    _step5_generate_advice(config, t_minus_1, risk_signals)

    dispose_engine()
    logger.info(f"{t_minus_1_str} 每日流程完成")


# ── STEP 1 ──

def _step1_sync_data(config: AppConfig, calendar: TradingCalendarService) -> None:
    """STEP 1：通过 DataManager 同步行情与基础数据。"""
    fetcher = DailyFetcher()
    dm = DataManager(config, fetcher, calendar)
    dm.sync_daily()


# ── STEP 2 ──

def _step2_calc_indicators(config: AppConfig, t_minus_1: date) -> None:
    """STEP 2：注册指标计算器，计算并保存 T-1 日指标。"""
    service = IndicatorService()
    service.register(MASystem(
        ma_short=config.strategy_params.get("ma_short", 20),
        ma_long=config.strategy_params.get("ma_long", 60),
    ))
    service.register(MACD())
    for etf in config.etf_list:
        n = service.calculate_and_save(etf.symbol, t_minus_1, t_minus_1)
        logger.info(f"STEP2: {etf.symbol} 写入 {n} 条指标")


# ── STEP 3 ──

def _step3_generate_signals(config: AppConfig, t_minus_1: date) -> None:
    """STEP 3：使用策略从指标生成信号并存入数据库。"""
    strategy = create_strategy(config)
    fetch_start = t_minus_1 - timedelta(days=10)

    for etf in config.etf_list:
        indicators = indicators_repo.find_by_code_between(
            etf.symbol, fetch_start, t_minus_1
        )
        if not indicators:
            logger.warning(f"STEP3: {etf.symbol} 无指标数据，跳过")
            continue

        df = _indicators_to_dataframe(indicators)
        signal_df = strategy.generate(df)

        target_str = str(t_minus_1)
        today = signal_df[signal_df["date"] == target_str]
        if today.empty:
            logger.warning(f"STEP3: {etf.symbol} {target_str} 无信号")
            continue

        for _, row in today.iterrows():
            signals_repo.save(
                code=etf.symbol,
                date=t_minus_1,
                signal=row["signal"],
                version=row["strategy_version"],
                meta=row["signal_meta"],
            )
            logger.info(
                f"STEP3: {etf.symbol} {target_str} "
                f"signal={row['signal']} meta={row['signal_meta']}"
            )


def _indicators_to_dataframe(indicators: list) -> pd.DataFrame:
    """将 ORM 指标对象列表转为展平 DataFrame。"""
    rows = []
    for ind in indicators:
        row = {"code": ind.code, "date": str(ind.date)}
        row.update(ind.data)
        rows.append(row)
    return pd.DataFrame(rows)


# ── STEP 4 ──

def _step4_risk_check() -> dict[str, dict]:
    """检查所有持仓，返回触发风控的信号 {code: {signal, source}}。"""
    positions = positions_repo.find_all()
    if not positions:
        logger.info("STEP4: 无持仓，跳过风控检查")
        return {}

    controller = RiskController(load_config())
    risk_signals: dict[str, dict] = {}

    for pos in positions:
        latest = quote_repo.find_latest_quote(pos.code)
        if latest is None:
            logger.warning(f"STEP4: {pos.code} 无行情数据，跳过风控")
            continue

        pos_dict = {
            "id": pos.id,
            "code": pos.code,
            "cost": float(pos.cost),
            "shares": pos.shares,
            "entry_date": str(pos.entry_date),
        }
        result = controller.check_position(pos_dict, latest.close)
        if result is not None:
            logger.info(f"STEP4: {pos.code} 触发风控 — {result.reason}")
            risk_signals[pos.code] = {"signal": result.signal, "source": result.source}

    return risk_signals


# ── STEP 5 ──

def _step5_generate_advice(config: AppConfig, t_minus_1: date,
                           risk_signals: dict[str, dict]) -> None:
    """STEP 5：综合信号与持仓生成操作建议并入库。"""
    positions = positions_repo.find_all()
    pos_list = [
        {
            "id": p.id, "code": p.code,
            "cost": float(p.cost), "shares": p.shares,
            "entry_date": str(p.entry_date),
        }
        for p in positions
    ]

    all_signals = signals_repo.find_by_date(t_minus_1)
    signal_rows = [
        {
            "code": s.code, "date": str(s.date),
            "signal": s.signal, "signal_meta": s.signal_meta,
        }
        for s in all_signals
    ]

    if not signal_rows:
        logger.warning("STEP5: 无信号数据，跳过建议生成")
        return

    current_prices: dict[str, float] = {}
    for etf in config.etf_list:
        latest = quote_repo.find_latest_quote(etf.symbol)
        if latest is not None:
            current_prices[etf.symbol] = latest.close

    advices = generate_advice(
        pos_list, pd.DataFrame(signal_rows), current_prices, risk_signals
    )
    records = [OperationAdvice(**a) for a in advices]
    advice_repo.save_batch(records)
    logger.info(f"STEP5: 写入 {len(records)} 条操作建议")


if __name__ == "__main__":
    run_daily()
