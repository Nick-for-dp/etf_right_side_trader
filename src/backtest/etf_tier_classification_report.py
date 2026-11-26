"""ETF strategy-tier classification and universe comparison report."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from src.backtest.ablation_config import (
    HIGH_VOL_QUALITY_BUDGET_TIER,
    SIGNAL_PROFILE_HIGH_VOL_BALANCED,
    production_v2_4_experiment,
)
from src.backtest.ablation_report import run_ablation_backtest
from src.backtest.portfolio_metrics import pair_closed_trades
from src.config import EtfItem
from src.service.calendar_service import TradingCalendarService

PRODUCTION_NAME = "v2_5_limited"


@dataclass(frozen=True)
class EtfTierProfile:
    """Manual strategy profile for first-layer ETF universe experiments."""

    symbol: str
    name: str
    strategy_tier: str
    prior_tier: str
    asset_class: str
    theme_primary: str
    theme_secondary: str
    reason: str
    long_cycle_reason: str = ""


_PROFILE_OVERRIDES: dict[str, dict[str, str]] = {
    "588000": {"tier": "A", "asset": "equity", "primary": "科技成长", "secondary": "科创宽基", "reason": "高弹性科技宽基，适合右侧趋势捕捉。"},
    "513180": {"tier": "A", "asset": "equity_hk", "primary": "科技成长", "secondary": "港股科技", "reason": "跨境高 beta 成长资产，趋势阶段弹性高。"},
    "513100": {"tier": "A", "asset": "equity_us", "primary": "海外成长", "secondary": "纳指100", "reason": "长期趋势属性较强，适合作为跨市场右侧核心。"},
    "159949": {"tier": "A", "asset": "equity", "primary": "科技成长", "secondary": "创业板宽基", "reason": "成长宽基，趋势弹性和资金承接较好。"},
    "512480": {"tier": "A", "asset": "equity", "primary": "科技成长", "secondary": "半导体", "reason": "高 beta 科技赛道，适合趋势确认后交易。"},
    "515050": {"tier": "A", "asset": "equity", "primary": "科技成长", "secondary": "通信", "reason": "科技基础设施方向，趋势阶段弹性较强。"},
    "512880": {"tier": "A", "asset": "equity", "primary": "金融弹性", "secondary": "证券", "reason": "券商 beta 高，右侧信号通常更有交易价值。"},

    "159227": {"tier": "B", "asset": "equity", "primary": "高端制造", "secondary": "航空航天", "reason": "主题弹性强，但样本短且波动高，适合作卫星。"},
    "515700": {"tier": "B", "asset": "equity", "primary": "新能源", "secondary": "新能源车", "reason": "强周期成长赛道，适合分组调参。"},
    "159755": {"tier": "B", "asset": "equity", "primary": "新能源", "secondary": "电池", "reason": "新能源链高波动，需用质量和主题热度约束。"},
    "159278": {"tier": "B", "asset": "equity", "primary": "高端制造", "secondary": "机器人", "reason": "成长主题较强，但上市时间短，暂作卫星。"},
    "515790": {"tier": "B", "asset": "equity", "primary": "新能源", "secondary": "光伏", "reason": "趋势机会存在，但长期下行样本多，需主题热度过滤。"},
    "159805": {"tier": "B", "asset": "equity", "primary": "数字经济", "secondary": "传媒", "reason": "主题波动大，适合事件后右侧但不宜核心化。"},
    "159870": {"tier": "B", "asset": "equity", "primary": "周期资源", "secondary": "化工", "reason": "周期属性明确，适合按周期热度调参。"},
    "512400": {"tier": "B", "asset": "equity", "primary": "周期资源", "secondary": "有色金属", "reason": "商品周期高弹性，但止损和再入场需单独观察。"},
    "561360": {"tier": "B", "asset": "equity", "primary": "周期资源", "secondary": "石油", "reason": "资源品趋势性强，但受外部商品周期驱动。"},
    "515220": {"tier": "B", "asset": "equity", "primary": "周期资源", "secondary": "煤炭", "reason": "周期和红利属性混合，适合作卫星而非核心。"},
    "515210": {"tier": "B", "asset": "equity", "primary": "周期资源", "secondary": "钢铁", "reason": "周期品，趋势窗口短，需降低优先级。"},
    "516970": {"tier": "B", "asset": "equity", "primary": "稳增长周期", "secondary": "基建", "reason": "政策周期驱动，适合主题热度确认后交易。"},
    "512170": {"tier": "B", "asset": "equity", "primary": "消费医药", "secondary": "医疗", "reason": "长期下行后可能有趋势修复，但需低优先级验证。"},
    "159992": {"tier": "B", "asset": "equity", "primary": "消费医药", "secondary": "创新药", "reason": "高波医药成长主题，适合卫星观察。"},
    "159326": {"tier": "B", "asset": "equity", "primary": "电力设备", "secondary": "电网设备", "reason": "设备链有主题趋势属性，不等同于防御型电力运营。"},

    "159611": {"tier": "C", "asset": "equity", "primary": "防御公用", "secondary": "电力运营", "reason": "偏公用事业和防御属性，趋势弹性可能不足。"},
    "159825": {"tier": "C", "asset": "equity", "primary": "防御消费", "secondary": "农业", "reason": "偏防御和均值回复，右侧趋势效率存疑。"},
    "159996": {"tier": "C", "asset": "equity", "primary": "消费稳定", "secondary": "家电", "reason": "低 beta 稳定消费属性较强，右侧弹性有限。"},
    "510150": {"tier": "C", "asset": "equity", "primary": "消费稳定", "secondary": "消费80", "reason": "消费稳定风格，右侧趋势交易优先级较低。"},
}


def classify_etf(item: EtfItem) -> EtfTierProfile:
    """Return the first-layer A/B/C strategy profile for one configured ETF."""

    override = _PROFILE_OVERRIDES.get(item.symbol)
    if override is not None:
        return EtfTierProfile(
            symbol=item.symbol,
            name=item.name,
            strategy_tier=override["tier"],
            prior_tier=override["tier"],
            asset_class=override["asset"],
            theme_primary=override["primary"],
            theme_secondary=override["secondary"],
            reason=override["reason"],
        )

    sector = item.sector
    theme = item.theme
    text = f"{item.name} {sector} {theme}"
    if any(key in text for key in ("银行", "红利", "低波", "电力", "公用")):
        tier = "C"
        primary = "防御稳定"
        reason = "防御或低波属性较强，先放入 C 类观察。"
    elif any(key in text for key in ("科技", "半导体", "通信", "证券", "创业", "科创", "纳指")):
        tier = "A"
        primary = "科技成长"
        reason = "高 beta 或成长属性较强，先放入 A 类核心候选。"
    else:
        tier = "B"
        primary = sector or "主题卫星"
        reason = "主题或周期属性明确，先放入 B 类卫星候选。"
    return EtfTierProfile(
        symbol=item.symbol,
        name=item.name,
        strategy_tier=tier,
        prior_tier=tier,
        asset_class="equity",
        theme_primary=primary,
        theme_secondary=theme or sector,
        reason=reason,
    )


def run_etf_tier_classification_backtest(
    codes: list[str] | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """Run v2.5 limited on full/A+B/A/B/C universes."""

    from src.config import load_config

    config = load_config()
    selected_codes = set(codes or [item.symbol for item in config.etf_list])
    profiles = [
        classify_etf(item)
        for item in config.etf_list
        if item.symbol in selected_codes
    ]
    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())

    experiment = _production_v25_experiment()
    single_evaluations = _run_long_cycle_single_etf_evaluations(
        profiles=profiles,
        end=end,
        capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        experiment=experiment,
    )
    profiles = _apply_long_cycle_tiers(profiles, single_evaluations)
    codes_by_tier = {
        tier: [profile.symbol for profile in profiles if profile.strategy_tier == tier]
        for tier in ("A", "B", "C")
    }
    universe_specs = [
        ("full", "全池", [profile.symbol for profile in profiles]),
        ("tier_ab", "A+B排除C", codes_by_tier["A"] + codes_by_tier["B"]),
        ("tier_a", "A类核心", codes_by_tier["A"]),
        ("tier_b", "B类卫星", codes_by_tier["B"]),
        ("tier_c", "C类观察", codes_by_tier["C"]),
    ]

    windows = [
        ("2016-2026", date(2016, 1, 1), end),
        ("2024-2026", date(2024, 1, 1), end),
    ]
    window_results = []
    for label, start, window_end in windows:
        rows = []
        for name, universe_label, universe_codes in universe_specs:
            if not universe_codes:
                continue
            result = run_ablation_backtest(
                codes=universe_codes,
                start=start,
                end=window_end,
                capital=capital,
                cost_ratio=cost_ratio,
                slippage=slippage,
                position_limit=position_limit,
                experiments=[experiment],
                matrix=f"etf-tier-classification-{name}",
            )
            version = result.get("versions", {}).get(PRODUCTION_NAME)
            if version is None:
                continue
            rows.append({
                "name": name,
                "label": universe_label,
                "codes": universe_codes,
                "summary": version.get("summary", {}),
                "stats": version.get("stats", {}),
                "tier_attribution": (
                    _tier_trade_attribution(version, profiles)
                    if name == "full" else {}
                ),
            })
        window_results.append({
            "label": label,
            "start": start,
            "end": window_end,
            "rows": rows,
            "decision": _window_decision(rows),
        })

    return {
        "meta": {
            "codes": [profile.symbol for profile in profiles],
            "capital": capital,
            "cost_ratio": cost_ratio,
            "slippage": slippage,
            "position_limit": position_limit,
            "matrix": "etf-tier-classification",
        },
        "profiles": profiles,
        "single_evaluations": single_evaluations,
        "codes_by_tier": codes_by_tier,
        "windows": window_results,
    }


def format_etf_tier_classification_report(result: dict[str, Any]) -> str:
    """Format ETF tier classification and universe comparison."""

    meta = result["meta"]
    lines: list[str] = []
    lines.append("=" * 150)
    lines.append("  ETF A/B/C 分类与交易池实验报告")
    lines.append("=" * 150)
    lines.append(f"  版本: v2.5 limited")
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  单 ETF 仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("  分类口径: 主题只作解释；A/B/C 由 2016-2026 单 ETF 长周期回测指标决定。")
    lines.append("")
    _append_single_evaluation_table(lines, result.get("single_evaluations", []))
    _append_profile_table(lines, result.get("profiles", []))
    for window in result.get("windows", []):
        _append_window(lines, window)
    lines.append("  说明:")
    lines.append("  - 各交易池都使用 100,000 元初始资金，比较的是不同 ETF universe 的资金效率。")
    lines.append("  - A 类需要长周期单 ETF 指标达标；近三年热门主题不能直接升为核心。")
    lines.append("  - 若长周期 A+B 明显优于全池，才考虑把 C 类从交易池降级到观察池。")
    return "\n".join(lines)


def _append_single_evaluation_table(lines: list[str], rows: list[dict[str, Any]]) -> None:
    headers = ["长周期层级", "先验", "代码", "名称", "年化", "回撤", "Calmar", "PF", "交易", "判定"]
    cols = [10, 4, 8, 18, 9, 9, 8, 8, 6, 42]
    lines.append("  单 ETF 长周期资格评估")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in sorted(rows, key=lambda item: (item["tier"], item["symbol"])):
        summary = row.get("summary", {})
        lines.append(
            f"  {row['tier']:10s}"
            f" {row.get('prior_tier', ''):4s}"
            f" {row['symbol']:8s}"
            f" {row['name'][:18]:18s}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
            f" {row.get('reason', '')[:42]:42s}"
        )
    lines.append("")


def _append_profile_table(lines: list[str], profiles: list[EtfTierProfile]) -> None:
    headers = ["层级", "先验", "代码", "名称", "一级主题", "二级主题", "分类理由"]
    cols = [4, 4, 8, 18, 12, 14, 48]
    lines.append("  ETF 长周期画像")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for profile in sorted(profiles, key=lambda item: (item.strategy_tier, item.symbol)):
        lines.append(
            f"  {profile.strategy_tier:4s}"
            f" {profile.prior_tier:4s}"
            f" {profile.symbol:8s}"
            f" {profile.name[:18]:18s}"
            f" {profile.theme_primary[:12]:12s}"
            f" {profile.theme_secondary[:14]:14s}"
            f" {(profile.long_cycle_reason or profile.reason)[:48]:48s}"
        )
    lines.append("")


def _append_window(lines: list[str], window: dict[str, Any]) -> None:
    lines.append(f"  区间: {window['label']} ({window['start']} ~ {window['end']})")
    rows = window.get("rows", [])
    full = _row_by_name(rows, "full")
    headers = ["交易池", "ETF", "年化", "较全池", "回撤", "回撤改善", "Calmar", "Sharpe", "胜率", "PF", "交易"]
    cols = [12, 4, 9, 9, 9, 9, 8, 8, 9, 8, 6]
    lines.append("  分层交易池对比")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for row in rows:
        summary = row["summary"]
        lines.append(
            f"  {row['label'][:12]:12s}"
            f" {len(row['codes']):>4d}"
            f" {_metric(summary, 'annual_return'):>9s}"
            f" {_delta_pct(summary, full['summary'], 'annual_return', lower_is_better=False) if full else 'N/A':>9s}"
            f" {_metric(summary, 'max_drawdown'):>9s}"
            f" {_delta_pct(summary, full['summary'], 'max_drawdown', lower_is_better=True) if full else 'N/A':>9s}"
            f" {summary.get('calmar', 'N/A'):>8s}"
            f" {summary.get('sharpe', 'N/A'):>8s}"
            f" {_metric(summary, 'win_rate'):>9s}"
            f" {summary.get('profit_factor', 'N/A'):>8s}"
            f" {summary.get('total_trades', 'N/A'):>6s}"
        )
    lines.append(f"  判断: {window.get('decision', '待判断')}")
    full = _row_by_name(rows, "full")
    if full is not None:
        _append_tier_attribution(lines, full.get("tier_attribution", {}))
    lines.append("")


def _append_tier_attribution(lines: list[str], attribution: dict[str, dict[str, Any]]) -> None:
    if not attribution:
        return
    headers = ["层级", "交易", "胜率", "已实现损益", "平均收益率", "PF"]
    cols = [4, 6, 8, 12, 10, 8]
    lines.append("  全池内 A/B/C 闭合交易归因")
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))
    for tier in ("A", "B", "C", "UNKNOWN"):
        row = attribution.get(tier)
        if row is None or row.get("count", 0) == 0:
            continue
        lines.append(
            f"  {tier:4s}"
            f" {row['count']:>6d}"
            f" {_fmt_pct(row.get('win_rate')):>8s}"
            f" {_fmt_money(row.get('pnl_cash_total'), signed=True):>12s}"
            f" {_fmt_pct(row.get('pnl_pct_avg'), signed=True):>10s}"
            f" {_fmt_number(row.get('profit_factor')):>8s}"
        )
    lines.append("")


def _production_v25_experiment():
    return production_v2_4_experiment(
        name=PRODUCTION_NAME,
        label="v2.5 limited",
        experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
        high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
        description="当前生产基线 v2.5 limited。",
    )


def _run_long_cycle_single_etf_evaluations(
    *,
    profiles: list[EtfTierProfile],
    end: date,
    capital: float,
    cost_ratio: float,
    slippage: float,
    position_limit: float,
    experiment,
) -> list[dict[str, Any]]:
    rows = []
    for profile in profiles:
        result = run_ablation_backtest(
            codes=[profile.symbol],
            start=date(2016, 1, 1),
            end=end,
            capital=capital,
            cost_ratio=cost_ratio,
            slippage=slippage,
            position_limit=position_limit,
            experiments=[experiment],
            matrix="etf-tier-single-long-cycle",
        )
        version = result.get("versions", {}).get(PRODUCTION_NAME, {})
        summary = version.get("summary", {})
        tier, reason = _long_cycle_tier(summary)
        rows.append({
            "symbol": profile.symbol,
            "name": profile.name,
            "prior_tier": profile.prior_tier,
            "tier": tier,
            "reason": reason,
            "summary": summary,
        })
    return rows


def _apply_long_cycle_tiers(
    profiles: list[EtfTierProfile],
    evaluations: list[dict[str, Any]],
) -> list[EtfTierProfile]:
    evaluation_by_code = {row["symbol"]: row for row in evaluations}
    result = []
    for profile in profiles:
        evaluation = evaluation_by_code.get(profile.symbol, {})
        tier = evaluation.get("tier", profile.strategy_tier)
        reason = evaluation.get("reason", profile.reason)
        result.append(EtfTierProfile(
            symbol=profile.symbol,
            name=profile.name,
            strategy_tier=tier,
            prior_tier=profile.prior_tier,
            asset_class=profile.asset_class,
            theme_primary=profile.theme_primary,
            theme_secondary=profile.theme_secondary,
            reason=profile.reason,
            long_cycle_reason=reason,
        ))
    return result


def _long_cycle_tier(summary: dict[str, Any]) -> tuple[str, str]:
    annual = _parse_percent(summary.get("annual_return"))
    drawdown = _parse_percent(summary.get("max_drawdown"))
    calmar = _parse_number(summary.get("calmar"))
    profit_factor = _parse_number(summary.get("profit_factor"))
    trades = _parse_int(summary.get("total_trades"))

    if None in (annual, drawdown, calmar, profit_factor) or trades is None:
        return "C", "长周期指标不足或无有效交易，降为观察。"

    # 单 ETF 评估仍受 30% 单标仓位上限约束，收益会被现金稀释；
    # 因此核心标准看资本受限后的稳定资金效率，而不是全仓年化。
    if (
        annual >= 0.025
        and drawdown <= 0.12
        and calmar >= 0.30
        and profit_factor >= 2.00
        and trades >= 20
    ):
        return "A", "30%仓位约束下长周期收益、回撤、Calmar、PF 和交易数均达核心标准。"

    if (
        annual >= 0.010
        and drawdown <= 0.20
        and calmar >= 0.15
        and profit_factor >= 1.50
        and trades >= 12
    ):
        return "B", "长周期有正向交易价值，但未达到核心标准。"

    return "C", "长周期收益、回撤、Calmar、PF 或交易数未达右侧核心要求。"


def _tier_trade_attribution(
    version: dict[str, Any],
    profiles: list[EtfTierProfile],
) -> dict[str, dict[str, Any]]:
    tier_by_code = {
        profile.symbol: profile.strategy_tier
        for profile in profiles
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trade in pair_closed_trades(version.get("trades", [])):
        tier = tier_by_code.get(trade["code"], "UNKNOWN")
        grouped.setdefault(tier, []).append(trade)

    result: dict[str, dict[str, Any]] = {}
    for tier, items in grouped.items():
        wins = [item for item in items if item["pnl_cash"] > 0]
        gains = sum(item["pnl_cash"] for item in items if item["pnl_cash"] > 0)
        losses = abs(sum(item["pnl_cash"] for item in items if item["pnl_cash"] < 0))
        result[tier] = {
            "count": len(items),
            "win_rate": len(wins) / len(items) if items else None,
            "pnl_cash_total": sum(item["pnl_cash"] for item in items),
            "pnl_pct_avg": (
                sum(item["pnl_pct"] for item in items) / len(items)
                if items else None
            ),
            "profit_factor": gains / losses if losses > 0 else None,
        }
    return result


def _window_decision(rows: list[dict[str, Any]]) -> str:
    full = _row_by_name(rows, "full")
    ab = _row_by_name(rows, "tier_ab")
    c = _row_by_name(rows, "tier_c")
    if full is None or ab is None:
        return "待判断"
    full_summary = full["summary"]
    ab_summary = ab["summary"]
    full_annual = _parse_percent(full_summary.get("annual_return"))
    ab_annual = _parse_percent(ab_summary.get("annual_return"))
    full_drawdown = _parse_percent(full_summary.get("max_drawdown"))
    ab_drawdown = _parse_percent(ab_summary.get("max_drawdown"))
    full_calmar = _parse_number(full_summary.get("calmar"))
    ab_calmar = _parse_number(ab_summary.get("calmar"))
    if None in (full_annual, ab_annual, full_drawdown, ab_drawdown, full_calmar, ab_calmar):
        return "待判断"
    if ab_annual > full_annual and ab_drawdown < full_drawdown and ab_calmar > full_calmar:
        return "A+B 排除 C 同时提升收益、回撤和 Calmar，C 类可进入降级候选。"
    if c is not None and _parse_number(c["summary"].get("calmar")) is not None:
        c_calmar = _parse_number(c["summary"].get("calmar"))
        if c_calmar is not None and c_calmar < full_calmar * 0.7:
            return "C 类资金效率弱于全池，但 A+B 未全面胜出，先做单 ETF 归因再决定。"
    return "长周期 A/B/C 分层尚未证明直接优于全池，需要继续验证分层资金配置和主题参数。"


def _row_by_name(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for row in rows:
        if row["name"] == name:
            return row
    return None


def _metric(summary: dict[str, Any], key: str) -> str:
    return str(summary.get(key, "N/A"))


def _delta_pct(
    summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    key: str,
    *,
    lower_is_better: bool,
) -> str:
    current = _parse_percent(summary.get(key))
    baseline = _parse_percent(baseline_summary.get(key))
    if current is None or baseline is None:
        return "N/A"
    delta = baseline - current if lower_is_better else current - baseline
    return f"{delta * 100:+.2f}%"


def _parse_percent(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "N/A":
        return None
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2%}" if signed else f"{value:.2%}"


def _fmt_money(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+,.0f}" if signed else f"{value:,.0f}"


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"
