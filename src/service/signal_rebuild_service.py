"""重建 signals 表的服务。

只使用现有 indicators 与 quote.close 重算策略信号，不改 quote / indicators。
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.config import AppConfig
from src.database import advice_repo, indicators_repo, quote_repo, signals_repo
from src.models import Signal
from src.runner.daily_runner import _step5_generate_advice
from src.strategy import create_strategy
from src.utils import get_logger

logger = get_logger(__name__)


@dataclass
class CodeRebuildStats:
    """单只 ETF 的重算结果。"""

    code: str
    indicators: int = 0
    quotes: int = 0
    generated: int = 0
    saved: int = 0
    skipped_missing_close: int = 0
    signal_counts: Counter = field(default_factory=Counter)
    versions: Counter = field(default_factory=Counter)
    latest_signal_date: date | None = None
    warning: str = ""


@dataclass
class RebuildSignalsResult:
    """signals 重建结果汇总。"""

    start: date
    end: date
    codes: list[str]
    dry_run: bool
    before_signals: int
    before_advice: int
    deleted_signals: int = 0
    deleted_advice: int = 0
    saved_signals: int = 0
    rebuilt_latest_advice_date: date | None = None
    code_stats: list[CodeRebuildStats] = field(default_factory=list)

    @property
    def signal_counts(self) -> Counter:
        result = Counter()
        for stats in self.code_stats:
            result.update(stats.signal_counts)
        return result

    @property
    def versions(self) -> Counter:
        result = Counter()
        for stats in self.code_stats:
            result.update(stats.versions)
        return result


def rebuild_signals(
    config: AppConfig,
    start: date,
    end: date,
    codes: list[str] | None = None,
    *,
    dry_run: bool = False,
    rebuild_latest_advice: bool = True,
) -> RebuildSignalsResult:
    """按范围删除并重建 signals。

    Args:
        config: 应用配置
        start: 起始日期（含）
        end: 截止日期（含）
        codes: ETF 代码列表，None 时覆盖配置中全部 ETF
        dry_run: 只统计将要执行的操作，不删除、不写入
        rebuild_latest_advice: 重算区间内最后一个交易日的 operation_advice
    """
    if start > end:
        raise ValueError("start 必须早于或等于 end")

    target_codes = codes or [e.symbol for e in config.etf_list]
    known_codes = {e.symbol for e in config.etf_list}
    unknown = [code for code in target_codes if code not in known_codes]
    if unknown:
        raise ValueError(f"ETF 不在 settings.yaml 中: {', '.join(unknown)}")

    before_signals = signals_repo.count_by_codes_between(target_codes, start, end)
    before_advice = advice_repo.count_by_codes_between(target_codes, start, end)
    result = RebuildSignalsResult(
        start=start,
        end=end,
        codes=target_codes,
        dry_run=dry_run,
        before_signals=before_signals,
        before_advice=before_advice,
    )

    strategy = create_strategy(config)
    signal_records: list[Signal] = []

    for code in target_codes:
        stats = _generate_code_signals(code, start, end, strategy, signal_records)
        result.code_stats.append(stats)

    result.saved_signals = len(signal_records)

    if dry_run:
        return result

    logger.info(
        "删除旧 signals: codes=%s start=%s end=%s existing=%s",
        len(target_codes), start, end, before_signals,
    )
    result.deleted_signals = signals_repo.delete_by_codes_between(target_codes, start, end)
    signals_repo.save_batch(signal_records)
    for stats in result.code_stats:
        stats.saved = stats.generated

    if rebuild_latest_advice:
        latest_signal_date = _find_latest_signal_date(result.code_stats, end)
        if latest_signal_date is not None:
            result.deleted_advice = advice_repo.delete_by_codes_between(
                target_codes, latest_signal_date, latest_signal_date
            )
            _step5_generate_advice(config, latest_signal_date, risk_signals={})
            result.rebuilt_latest_advice_date = latest_signal_date

    return result


def format_rebuild_signals_report(result: RebuildSignalsResult) -> str:
    """格式化重建报告。"""
    lines = []
    mode = "DRY RUN" if result.dry_run else "EXECUTE"
    lines.append("=" * 72)
    lines.append(f"  signals 重建报告 ({mode})")
    lines.append("=" * 72)
    lines.append(f"  区间: {result.start} ~ {result.end}")
    lines.append(f"  ETF 数量: {len(result.codes)}")
    lines.append(f"  原 signals: {result.before_signals}")
    lines.append(f"  原 advice:  {result.before_advice}")
    if not result.dry_run:
        lines.append(f"  删除 signals: {result.deleted_signals}")
        lines.append(f"  删除 latest advice: {result.deleted_advice}")
    lines.append(f"  生成 signals: {result.saved_signals}")
    lines.append(f"  signal 分布: {dict(result.signal_counts)}")
    lines.append(f"  version 分布: {dict(result.versions)}")
    if result.rebuilt_latest_advice_date is not None:
        lines.append(f"  已重算最新 advice: {result.rebuilt_latest_advice_date}")
    lines.append("")
    lines.append("  代码      指标数  行情数  生成数  缺 close  分布")
    lines.append("  " + "-" * 62)
    for stats in result.code_stats:
        warning = f"  WARN={stats.warning}" if stats.warning else ""
        lines.append(
            f"  {stats.code:6s}  {stats.indicators:5d}  {stats.quotes:5d}"
            f"  {stats.generated:5d}  {stats.skipped_missing_close:7d}"
            f"  {dict(stats.signal_counts)}{warning}"
        )
    return "\n".join(lines)


def _generate_code_signals(
    code: str,
    start: date,
    end: date,
    strategy,
    sink: list[Signal],
) -> CodeRebuildStats:
    stats = CodeRebuildStats(code=code)
    indicators = indicators_repo.find_by_code_between(code, start, end)
    quotes = quote_repo.find_by_code_in_range(code, start, end)
    stats.indicators = len(indicators)
    stats.quotes = len(quotes)

    if not indicators:
        stats.warning = "no_indicators"
        return stats
    if not quotes:
        stats.warning = "no_quotes"
        return stats

    close_map = {str(q.date): q.close for q in quotes}
    rows = []
    for ind in indicators:
        row = {"code": ind.code, "date": str(ind.date)}
        row.update(ind.data)
        row["close"] = close_map.get(str(ind.date))
        rows.append(row)

    df = pd.DataFrame(rows)
    stats.skipped_missing_close = int(df["close"].isna().sum())
    signal_df = strategy.generate(df)

    for _, row in signal_df.iterrows():
        signal_date = row["date"]
        if isinstance(signal_date, str):
            signal_date = date.fromisoformat(signal_date)
        if signal_date < start or signal_date > end:
            continue
        signal_value = row["signal"]
        version = row["strategy_version"]
        meta = row["signal_meta"] or {}
        sink.append(Signal(
            code=code,
            date=signal_date,
            signal=signal_value,
            strategy_version=version,
            signal_meta=meta,
        ))
        stats.generated += 1
        if stats.latest_signal_date is None or signal_date > stats.latest_signal_date:
            stats.latest_signal_date = signal_date
        stats.signal_counts[signal_value] += 1
        stats.versions[version] += 1

    return stats


def _find_latest_signal_date(stats: list[CodeRebuildStats], end: date) -> date | None:
    dates = [s.latest_signal_date for s in stats if s.latest_signal_date is not None]
    return max(dates) if dates else None
