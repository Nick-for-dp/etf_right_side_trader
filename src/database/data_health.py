"""数据健康检查：最新日期、断档与停更，异常时给出非零退出码。

用法:
    python main.py check-data

检查口径：
- 以 T-1 交易日为基准，回看最近 90 天；
- ETF 行情、指标、信号、建议逐代码核对缺失交易日；
- 指数行情核对是否停在 T-1 之前。
任一硬校验失败，进程返回退出码 1，供调度和人工巡检使用。
"""

from datetime import date, timedelta

from src.config import AppConfig
from src.database import (
    market_index_quote_repo,
    market_regime_repo,
    quote_repo,
    indicators_repo,
    signals_repo,
    advice_repo,
)
from src.service import TradingCalendarService
from src.utils import get_logger

logger = get_logger(__name__)

_WINDOW_DAYS = 90


def check_all(config: AppConfig, window_days: int = _WINDOW_DAYS) -> bool:
    """执行全部检查，返回是否通过（True = 无硬性问题）。"""
    calendar = TradingCalendarService()
    t_minus_1 = date.fromisoformat(calendar.get_previous_trading_day())
    window_start = t_minus_1 - timedelta(days=window_days)
    expected = {
        date.fromisoformat(d)
        for d in calendar.get_trading_days_in_range(window_start, t_minus_1)
    }

    print("=" * 72)
    print("  数据健康检查报告")
    print("=" * 72)
    print(f"  基准交易日 T-1: {t_minus_1}    检查窗口: {window_start} ~ {t_minus_1}")
    print()

    violations: list[str] = []
    violations += _check_quotes(config, expected, t_minus_1)
    violations += _check_index_quotes(config, t_minus_1)
    _check_market_regime(t_minus_1)
    violations += _check_derived(
        "技术指标", config, expected, t_minus_1,
        lambda code, start, end: indicators_repo.find_by_code_between(code, start, end),
    )
    violations += _check_derived(
        "交易信号", config, expected, t_minus_1,
        lambda code, start, end: signals_repo.find_by_code_between(code, start, end),
    )
    violations += _check_derived(
        "操作建议", config, expected, t_minus_1,
        lambda code, start, end: advice_repo.find_by_code_between(code, start, end),
    )

    print("=" * 72)
    if violations:
        print(f"  检查未通过：{len(violations)} 项")
        for item in violations[:20]:
            print(f"  - {item}")
        if len(violations) > 20:
            print(f"  ... 其余 {len(violations) - 20} 项略")
    else:
        print("  检查通过")
    print("=" * 72)
    return not violations


def _print_table(rows: list[list[str]], headers: list[str]) -> None:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    def fmt_row(cells: list[str]) -> str:
        return "  ".join(c.ljust(col_widths[j]) for j, c in enumerate(cells))

    print("  " + fmt_row(headers))
    print("  " + "-" * (sum(col_widths) + (len(headers) - 1) * 2))
    for row in rows:
        print("  " + fmt_row(row))
    print()


def _missing(dates: set[date], expected: set[date]) -> list[date]:
    return sorted(expected - dates)


def _check_quotes(config: AppConfig, expected: set[date], t_minus_1: date) -> list[str]:
    print(f"[ETF 行情] {len(config.etf_list)} 只")
    rows, problems = [], []
    for etf in config.etf_list:
        latest = quote_repo.find_latest_date(etf.symbol)
        earliest = quote_repo.find_earliest_date(etf.symbol)
        actual = {
            q.date for q in quote_repo.find_by_code_in_range(etf.symbol, min(expected), t_minus_1)
        }
        miss = _missing(actual, expected)
        status = "OK" if not miss else f"缺 {len(miss)} 天"
        if miss:
            problems.append(f"行情 {etf.symbol} 缺 {len(miss)} 个交易日（最近 {miss[-1]}）")
        rows.append([etf.symbol, str(earliest or "N/A"), str(latest or "N/A"), status])
    _print_table(rows, ["代码", "最早", "最新", f"近 {_WINDOW_DAYS} 天断档"])
    return problems


def _check_index_quotes(config: AppConfig, t_minus_1: date) -> list[str]:
    print(f"[指数行情] {len(config.market_indices)} 个")
    rows, problems = [], []
    today = date.today()
    for idx in config.market_indices:
        latest = market_index_quote_repo.find_latest_date(idx.code)
        expected = _index_expected_date(idx, today, t_minus_1)
        stale = latest is None or latest < expected
        if stale:
            problems.append(f"指数 {idx.code} 最新 {latest or 'N/A'} < {expected}")
        rows.append([idx.code, idx.name, idx.source, str(latest or "N/A"),
                     "STALE" if stale else "OK"])
    _print_table(rows, ["代码", "名称", "源", "最新", "状态"])
    return problems


def _index_expected_date(idx, today: date, fallback: date) -> date:
    """按指数所属市场的日历推算应有的最新交易日。

    A 股休市日与美股、港股不同（如美股感恩节休市），用 A 股 T-1 校验
    美股指数会误报停更，因此按 source 映射到对应交易所日历。
    """
    exchange = {
        "akshare_us": "XNYS",
        "tushare_global": "XHKG",
    }.get(idx.source)
    if exchange is None:
        return fallback
    try:
        cal = TradingCalendarService(exchange=exchange)
        prev = cal.get_previous_trading_day(today)
        return date.fromisoformat(prev) if prev else fallback
    except Exception as exc:  # 日历不可用时退回 A 股口径，只多报不误放
        logger.warning(f"指数 {idx.code} 日历 {exchange} 不可用: {exc}")
        return fallback



def _check_market_regime(t_minus_1: date) -> None:
    print("[市场状态]")
    latest = market_regime_repo.find_between(
        t_minus_1 - timedelta(days=30), t_minus_1
    )
    if latest:
        last = latest[-1]
        flag = "" if last.date == t_minus_1 else "（未到 T-1）"
        print(f"  最新: {last.date} state={last.state} score={last.score} {flag}")
    else:
        print("  最近 30 天无数据")
    print()


def _check_derived(
    title: str,
    config: AppConfig,
    expected: set[date],
    t_minus_1: date,
    loader,
) -> list[str]:
    print(f"[{title}] {len(config.etf_list)} 只")
    rows, problems = [], []
    start = min(expected)
    for etf in config.etf_list:
        records = loader(etf.symbol, start, t_minus_1)
        actual = {r.date for r in records}
        latest = max(actual) if actual else None
        miss = _missing(actual, expected)
        status = "OK" if not miss else f"缺 {len(miss)} 天"
        if miss:
            problems.append(f"{title} {etf.symbol} 缺 {len(miss)} 个交易日（最近 {miss[-1]}）")
        rows.append([etf.symbol, str(latest or "N/A"), status])
    _print_table(rows, ["代码", "最新", f"近 {_WINDOW_DAYS} 天断档"])
    return problems
