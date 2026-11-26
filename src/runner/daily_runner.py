"""每日流程（STEP 1-5）。

scheduler 与手工触发共用 run_daily。每个 STEP 的实现在本模块内唯一，
信号与建议的生成函数同时被 rebuild-signals 复用。
"""

from datetime import date, timedelta

import pandas as pd

from src.advisor import generate_advice
from src.config import load_config, AppConfig
from src.database import (
    init_engine, dispose_engine,
    advice_repo, positions_repo, quote_repo, signals_repo, trade_records_repo,
    market_regime_repo,
)
from src.fetcher import DailyFetcher, DataManager
from src.models import OperationAdvice
from src.risk import RiskController
from src.service import (
    TradingCalendarService,
    PositionService,
    MarketRegimeService,
)
from src.service.indicator_service import build_indicator_service
from src.service.market_regime_service import build_per_code_market_regime
from src.strategy import create_strategy
from src.utils import get_logger

logger = get_logger(__name__)


def run_daily(target_date: date | None = None, start_date: date | None = None) -> None:
    """把派生数据补到 T-1。

    从最后一个完整的派生日（operation_advice 最新日期）的下一个交易日开始，
    逐日补算 market_regime、风控信号与操作建议；指标和交易信号按区间一次算完。
    停机数周后执行一次即可追平。
    """
    config = load_config()
    init_engine(config.db_url)
    try:
        calendar = TradingCalendarService()
        t_minus_1 = date.fromisoformat(
            calendar.get_previous_trading_day(target_date or date.today())
        )
        logger.info(f"每日流程目标日: {t_minus_1}")

        _step1_sync_data(config, calendar)

        start = start_date or _next_pending_day(calendar, t_minus_1)
        if start is None:
            logger.info(f"派生数据已到 {t_minus_1}，无需补算")
            return

        days = [
            date.fromisoformat(d)
            for d in calendar.get_trading_days_in_range(start, t_minus_1)
        ]
        if not days:
            logger.info(f"暂无待补交易日（{start} ~ {t_minus_1}）")
            return
        logger.info(f"补算区间 {days[0]} ~ {days[-1]}，共 {len(days)} 个交易日")

        indicator_service = build_indicator_service(config)
        strategy = create_strategy(config)
        regime_service = (
            MarketRegimeService(config.market_indices, config.market_regime_params)
            if config.market_regime_params.get("enabled", True) else None
        )
        risk_controller = RiskController(config)

        _step2_calc_indicators(config, indicator_service, days[0], days[-1])
        _step3_generate_signals(config, strategy, days[0], days[-1])

        for day in days:
            _step2b_calc_market_regime(config, day, regime_service)
            risk_signals = _step4_risk_check(config, day, risk_controller)
            generate_advice_for_date(config, day, risk_signals)

        logger.info(f"{days[-1]} 每日流程完成")
    finally:
        dispose_engine()


def _next_pending_day(calendar: TradingCalendarService, t_minus_1: date) -> date | None:
    """返回需要补算的起始日期；已追平则返回 None。"""
    last = advice_repo.find_latest_date()
    if last is None:
        return t_minus_1
    if last >= t_minus_1:
        return None
    return last + timedelta(days=1)


# ── STEP 1：同步数据 ──

def _step1_sync_data(config: AppConfig, calendar: TradingCalendarService) -> None:
    fetcher = DailyFetcher()
    dm = DataManager(config, fetcher, calendar)
    dm.sync_daily()
    dm.sync_market_indices_daily()


# ── STEP 2：指标 ──

def _step2_calc_indicators(config: AppConfig, service, start: date, end: date) -> None:
    for etf in config.etf_list:
        n = service.calculate_and_save(etf.symbol, start, end)
        logger.info(f"STEP2: {etf.symbol} 写入 {n} 条指标（{start} ~ {end}）")


def _step2b_calc_market_regime(
    config: AppConfig,
    day: date,
    service: MarketRegimeService | None = None,
) -> None:
    if service is None:
        logger.info("STEP2B: 市场状态门控未启用，跳过")
        return
    regime = service.calculate_and_save(day)
    logger.info(f"STEP2B: market_regime {day} state={regime.state} score={regime.score}")


# ── STEP 3：信号 ──

def _step3_generate_signals(
    config: AppConfig,
    strategy,
    start: date,
    end: date,
) -> None:
    """生成 [start, end] 的信号并入库（与 rebuild-signals 同一实现）。"""
    from src.service.signal_rebuild_service import generate_code_signals

    total = 0
    for etf in config.etf_list:
        records, stats = generate_code_signals(etf.symbol, start, end, strategy)
        if stats.warning:
            logger.warning(f"STEP3: {etf.symbol} {stats.warning}")
            continue
        if records:
            signals_repo.save_batch(records)
            total += len(records)
    logger.info(f"STEP3: 写入 {total} 条信号（{start} ~ {end}）")


# ── STEP 4：风控 ──

def _step4_risk_check(
    config: AppConfig,
    day: date,
    controller: RiskController | None = None,
) -> dict[str, dict]:
    """检查所有持仓在 day 当日的风控状态，返回 {code: {signal, source, reason}}。"""
    from src.database import indicators_repo

    positions = positions_repo.find_all()
    if not positions:
        logger.info(f"STEP4: {day} 无持仓，跳过风控检查")
        return {}

    controller = controller or RiskController(config)
    stop_loss_profiles = {etf.symbol: etf.stop_loss_profile for etf in config.etf_list}
    risk_signals: dict[str, dict] = {}

    for pos in positions:
        latest = quote_repo.find_quote_on_or_before(pos.code, day)
        if latest is None:
            logger.warning(f"STEP4: {pos.code} 无 {day} 及之前的行情，跳过风控")
            continue

        ind_list = indicators_repo.find_by_code_between(pos.code, day, day)
        indicator_data = ind_list[0].data if ind_list else {}
        profile = stop_loss_profiles.get(pos.code, "fixed_8")

        result = controller.check_position(
            {
                "id": pos.id,
                "code": pos.code,
                "cost": float(pos.cost),
                "shares": pos.shares,
                "entry_date": pos.first_entry_date or pos.entry_date,
                "as_of_date": day,
                "atr_pct": indicator_data.get("atr_pct"),
                "stop_loss_profile": profile,
            },
            latest.close,
        )
        if result is not None:
            logger.info(f"STEP4: {pos.code} 触发风控 — {result.reason}")
            risk_signals[pos.code] = {
                "signal": result.signal,
                "source": result.source,
                "reason": result.reason,
                "stop_loss_profile": profile,
            }

    return risk_signals


# ── STEP 5：建议 ──

def generate_advice_for_date(
    config: AppConfig,
    t_minus_1: date,
    risk_signals: dict[str, dict] | None = None,
) -> int:
    """生成并写入某日操作建议，返回写入条数。"""
    risk_signals = risk_signals or {}
    positions = positions_repo.find_all()
    pos_list = [{
        "id": p.id, "code": p.code,
        "cost": float(p.cost), "shares": p.shares,
        "entry_date": str(p.entry_date),
    } for p in positions]
    position_entry_dates = {p.code: p.entry_date for p in positions}
    add_counts = {p.code: p.add_count or 0 for p in positions}

    all_signals = signals_repo.find_by_date(t_minus_1)
    signal_rows = [{
        "code": s.code, "date": str(s.date),
        "signal": s.signal, "signal_meta": s.signal_meta,
    } for s in all_signals]
    if not signal_rows:
        logger.warning("STEP5: 无信号数据，跳过建议生成")
        return 0

    current_prices: dict[str, float] = {}
    last_buy_dates: dict[str, date] = {}
    stop_loss_profiles = {etf.symbol: etf.stop_loss_profile for etf in config.etf_list}

    market_regime_record = market_regime_repo.find_by_date(t_minus_1)
    base_regime = (
        {
            "state": market_regime_record.state,
            "score": market_regime_record.score,
            "data": market_regime_record.data,
        }
        if market_regime_record is not None
        else {"state": "UNKNOWN"}
    )
    per_code_regime = build_per_code_market_regime(
        {etf.symbol: etf.regime_group for etf in config.etf_list},
        t_minus_1,
        base_regime,
        params=config.market_regime_params,
    )

    for etf in config.etf_list:
        latest = quote_repo.find_quote_on_or_before(etf.symbol, t_minus_1)
        if latest is not None:
            current_prices[etf.symbol] = latest.close
        last_buy_date = trade_records_repo.find_latest_buy_date(etf.symbol, t_minus_1)
        if last_buy_date is None:
            last_buy_date = position_entry_dates.get(etf.symbol)
        if last_buy_date is not None:
            last_buy_dates[etf.symbol] = last_buy_date

    advices = generate_advice(
        positions=pos_list,
        signals=pd.DataFrame(signal_rows),
        current_prices=current_prices,
        risk_signals=risk_signals,
        market_regime=per_code_regime,
        last_buy_dates=last_buy_dates,
        add_counts=add_counts,
        entry_add_budget=config.strategy_params.get("entry_add_budget", {}),
        entry_budget_overrides=config.strategy_params.get("entry_budget_overrides", {}),
        code_volatility_groups={etf.symbol: etf.volatility_group for etf in config.etf_list},
        stop_loss_profiles=stop_loss_profiles,
        add_cooldown_days=config.strategy_params.get("cooldown_days", 5),
        account_capital=config.account_capital,
        max_position_ratio=config.account_max_position_ratio,
    )
    records = [OperationAdvice(**a) for a in advices]
    advice_repo.save_batch(records)
    logger.info(f"STEP5: 写入 {len(records)} 条操作建议")
    return len(records)


if __name__ == "__main__":
    run_daily()
