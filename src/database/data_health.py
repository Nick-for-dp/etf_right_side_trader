"""数据健康检查：输出各数据域最新日期、覆盖区间和缺失情况。

用法:
    python main.py check-data

输出各表的汇总状态，帮助判断数据链路是否正常。
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
from src.utils import get_logger

logger = get_logger(__name__)


def check_all(config: AppConfig) -> None:
    """检查所有核心数据域的健康状态。"""
    print("=" * 72)
    print("  数据健康检查报告")
    print("=" * 72)
    print()

    _check_etf_quotes(config)
    _check_market_indices(config)
    _check_market_regime()
    _check_indicators(config)
    _check_signals(config)
    _check_advice(config)

    print("=" * 72)
    print("  检查完成")
    print("=" * 72)


def _print_table(rows: list[list[str]], headers: list[str]) -> None:
    """打印简单的对齐表格。"""
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


def _find_latest_date(symbol: str, kind: str) -> date | None:
    """通用的最新日期查找，适配不同 repo 的方法签名。"""
    today = date.today()
    start = today - timedelta(days=365)  # 查过去一年

    if kind == "signal":
        rows = signals_repo.find_by_code_between(symbol, start, today)
    elif kind == "indicator":
        rows = indicators_repo.find_by_code_between(symbol, start, today)
    elif kind == "advice":
        rows = advice_repo.find_by_code(symbol)
        rows = [r for r in rows if r.date >= start]
    else:
        return None

    if not rows:
        return None
    return max(r.date for r in rows)


def _check_etf_quotes(config: AppConfig) -> None:
    """检查 ETF 行情覆盖情况。"""
    print(f"[ETF 行情] 共 {len(config.etf_list)} 只")
    rows = []
    for etf in config.etf_list:
        latest = quote_repo.find_latest_date(etf.symbol)
        earliest = quote_repo.find_earliest_date(etf.symbol)
        if latest and earliest:
            days = (latest - earliest).days
            status = "OK"
        elif latest:
            days = 0
            status = "PARTIAL"
        else:
            days = 0
            status = "NO DATA"
        rows.append([
            etf.symbol,
            etf.name or "",
            status,
            str(earliest or "N/A"),
            str(latest or "N/A"),
            f"{days}天",
        ])
    _print_table(rows, ["代码", "名称", "状态", "最早", "最新", "跨度"])


def _check_market_indices(config: AppConfig) -> None:
    """检查指数行情覆盖情况。"""
    active = [i for i in config.market_indices if i.weight > 0]
    inactive = [i for i in config.market_indices if i.weight == 0]
    print(f"[指数行情] 共 {len(config.market_indices)} 个（热度评分 {len(active)} 个 + 观察 {len(inactive)} 个）")

    headers = ["代码", "名称", "源", "角色", "状态", "最早", "最新", "跨度"]
    rows = []
    for idx in config.market_indices:
        latest = market_index_quote_repo.find_latest_date(idx.code)
        earliest = None
        if latest:
            quotes = market_index_quote_repo.find_by_code_in_range(
                idx.code, latest - timedelta(days=720), latest
            )
            if quotes:
                earliest = quotes[0].date
        role = "评分" if idx.weight > 0 else "观察"
        if latest and earliest:
            days = (latest - earliest).days
            status = "OK"
        elif latest:
            days = 0
            status = "PARTIAL"
        else:
            days = 0
            status = "NO DATA"
        rows.append([
            idx.code,
            idx.name,
            idx.source,
            role,
            status,
            str(earliest or "N/A"),
            str(latest or "N/A"),
            f"{days}天",
        ])
    _print_table(rows, headers)


def _check_market_regime() -> None:
    """检查市场热度快照。"""
    print("[市场热度]")
    today = date.today()
    regimes = market_regime_repo.find_between(today - timedelta(days=30), today)
    if regimes:
        latest = regimes[-1]
        print(f"  最近 30 天共 {len(regimes)} 条记录")
        print(f"  最新: {latest.date}  state={latest.state}  score={latest.score}")
    else:
        print("  最近 30 天无数据")
    print()


def _check_indicators(config: AppConfig) -> None:
    """检查指标数据。"""
    print(f"[技术指标] {len(config.etf_list)} 只 ETF")
    rows = []
    for etf in config.etf_list:
        latest = _find_latest_date(etf.symbol, "indicator")
        rows.append([etf.symbol, str(latest or "N/A")])
    _print_table(rows, ["代码", "最新指标日期"])


def _check_signals(config: AppConfig) -> None:
    """检查信号数据。"""
    print(f"[交易信号] {len(config.etf_list)} 只 ETF")
    rows = []
    for etf in config.etf_list:
        latest = _find_latest_date(etf.symbol, "signal")
        rows.append([etf.symbol, str(latest or "N/A")])
    _print_table(rows, ["代码", "最新信号日期"])


def _check_advice(config: AppConfig) -> None:
    """检查操作建议。"""
    print(f"[操作建议] {len(config.etf_list)} 只 ETF")
    rows = []
    for etf in config.etf_list:
        latest = _find_latest_date(etf.symbol, "advice")
        rows.append([etf.symbol, str(latest or "N/A")])
    _print_table(rows, ["代码", "最新建议日期"])
