"""V2.0 vs V2.1A 赔率门控回测对比。

同一策略信号，不同 advisor 配置：
  - V2.0（无门控）: generate_advice(odds_map=None)
  - V2.1A（有门控）: generate_advice(odds_map=实际赔率数据)

对比两版交易表现，验证赔率门控是否减少追高交易、改善回撤。
纯内存计算，不修改数据库。
"""

from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.advisor import generate_advice
from src.config import load_config
from src.database import indicators_repo, market_regime_repo, quote_repo, signals_repo
from src.models import VirtualTrade
from src.service.calendar_service import TradingCalendarService
from src.service.profit_analysis_service import _simulate_trade_engine, get_summary
from src.service.backtest_comparison import _build_equity_curve_from_events
from src.strategy import create_strategy
from src.utils import get_logger

logger = get_logger(__name__)

# 单次模拟建仓的虚拟份额数（不影响百分比盈亏计算，仅用于均价重算）
_VIRTUAL_SHARES = 1000


class OddsGateBacktest:
    """V2.0 vs V2.1A 赔率门控回测引擎。

    核心逻辑：
      1. 加载历史指标 + 行情 → 策略生成信号
      2. 逐日推进信号，同一份信号分别走 v2.0 / v2.1A advisor
      3. 独立维护两版模拟持仓（赔率门控可能导致仓位分叉）
      4. 事件流输入 _simulate_trade_engine → 输出 VirtualTrade
      5. 汇总对比指标
    """

    def __init__(self, calendar: TradingCalendarService, cooldown_days: int = 5):
        self.calendar = calendar
        self.cooldown_days = cooldown_days

    # ── 数据加载 ──

    def load_data(
        self, codes: list[str], start: date, end: date
    ) -> tuple[
        pd.DataFrame,
        dict[str, dict[str, float]],
        dict[str, dict[str, dict]],
        dict[str, dict],
    ]:
        """从 indicators + quote + signals 表加载回测所需数据。

        策略信号从 signals 表读取（已持久化的生产信号），而非重新生成，
        确保回测信号与生产环境一致。

        Args:
            codes: ETF 代码列表
            start: 回测起始日期
            end:   回测结束日期

        Returns:
            (df, price_map, odds_map_full, market_regime_map):
            - df:           columns = [code, date, close, signal, signal_meta, ma20, ma60, ...]
            - price_map:    {code: {date_str: close}}
            - odds_map_full: {code: {date_str: {odds_state, odds_score, premium_blocked}}}
            - market_regime_map: {date_str: {state, score, data}}
        """
        fetch_start = start - timedelta(days=120)

        rows = []
        price_map: dict[str, dict[str, float]] = {}
        odds_map_full: dict[str, dict[str, dict]] = {}

        for code in codes:
            # 指标（含 odds 字段）
            indicators = indicators_repo.find_by_code_between(code, fetch_start, end)
            ind_by_date: dict[str, dict] = {}
            for ind in indicators:
                ind_by_date[str(ind.date)] = ind.data

            # 行情
            quotes = quote_repo.find_by_code_in_range(code, fetch_start, end)
            code_prices: dict[str, float] = {}
            for q in quotes:
                code_prices[str(q.date)] = float(q.close)
            price_map[code] = code_prices

            # 信号（从 DB 读取，确保与生产一致）
            db_signals = signals_repo.find_by_code_between(code, start, end)
            sig_by_date: dict[str, dict] = {}
            for s in db_signals:
                sig_by_date[str(s.date)] = {"signal": s.signal, "signal_meta": s.signal_meta}

            # 赔率数据
            code_odds: dict[str, dict] = {}
            for d_str, ind_data in ind_by_date.items():
                odds_state = ind_data.get("odds_state")
                if odds_state is not None:
                    code_odds[d_str] = {
                        "odds_state": odds_state,
                        "odds_score": ind_data.get("odds_score"),
                        "premium_blocked": ind_data.get("odds_premium_blocked", False),
                    }
            odds_map_full[code] = code_odds

            # 组装行：信号 + 指标 + close
            for d_str, sig in sig_by_date.items():
                close = code_prices.get(d_str)
                if close is None:
                    continue
                row = {
                    "code": code,
                    "date": d_str,
                    "close": close,
                    "signal": sig["signal"],
                    "signal_meta": sig["signal_meta"],
                }
                rows.append(row)

        df = pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)
        regimes = market_regime_repo.find_between(start, end)
        market_regime_map = {
            str(r.date): {"state": r.state, "score": r.score, "data": r.data}
            for r in regimes
        }
        return df, price_map, odds_map_full, market_regime_map

    # ── 单版本模拟 ──

    def _simulate_version(
        self,
        df: pd.DataFrame,
        price_map: dict[str, dict[str, float]],
        odds_map_full: dict[str, dict[str, dict]],
        use_odds_gate: bool,
        use_market_gate: bool = False,
        market_regime_map: dict[str, dict] | None = None,
    ) -> tuple[list[VirtualTrade], pd.DataFrame, dict]:
        """对指定版本（v2.0 或 v2.1A）运行完整交易模拟。

        Returns:
            (trades, equity_curve, stats):
            - trades:        所有代码的 VirtualTrade 列表
            - equity_curve:  多代码合并权益曲线 DataFrame
            - stats:         {buys_blocked, buy_events, add_events, sell_events,
                              open_positions, closed_trades}
        """
        empty_stats = {
            "buys_blocked": 0, "buy_events": 0, "add_events": 0,
            "sell_events": 0, "open_positions": 0, "closed_trades": 0,
            "market_blocked": 0,
        }
        if df.empty:
            return [], pd.DataFrame(), empty_stats

        # 模拟持仓
        sim_positions: dict[str, dict] = {}
        last_add_date: dict[str, date] = {}
        _pos_id = 1

        codes_events: dict[str, list[tuple[date, str, float, str]]] = {}
        buys_blocked = 0
        buy_events = 0
        add_events = 0
        sell_events = 0
        market_blocked = 0
        market_regime_map = market_regime_map or {}

        all_dates = sorted(df["date"].unique())

        for signal_date_str in all_dates:
            day_signals_df = df[df["date"] == signal_date_str]

            # 构建信号行（generate_advice 需要的 DataFrame 格式）
            signal_rows = []
            for _, row in day_signals_df.iterrows():
                signal_rows.append({
                    "code": row["code"],
                    "date": row["date"],
                    "signal": row["signal"],
                    "signal_meta": row.get("signal_meta", {}),
                })

            # 构建赔率 map（仅 v2.1A 使用）
            odds_map: dict[str, dict] = {}
            if use_odds_gate:
                for _, row in day_signals_df.iterrows():
                    code = row["code"]
                    code_odds = odds_map_full.get(code, {}).get(signal_date_str)
                    if code_odds:
                        odds_map[code] = code_odds

            # 调用 advisor。统计口径需要分离：赔率拦截只比较“无门控→赔率门控”，
            # 市场拦截只比较“赔率门控→赔率+市场门控”。
            pos_list = list(sim_positions.values())
            raw_advices = generate_advice(
                positions=pos_list,
                signals=pd.DataFrame(signal_rows),
                current_prices={},
                risk_signals={},
                odds_map=None,
                market_regime=None,
            )
            odds_only_advices = generate_advice(
                positions=pos_list,
                signals=pd.DataFrame(signal_rows),
                current_prices={},
                risk_signals={},
                odds_map=odds_map if use_odds_gate else None,
                market_regime=None,
            )
            advices = generate_advice(
                positions=pos_list,
                signals=pd.DataFrame(signal_rows),
                current_prices={},
                risk_signals={},
                odds_map=odds_map if use_odds_gate else None,
                market_regime=(
                    market_regime_map.get(signal_date_str)
                    if use_market_gate else None
                ),
            )

            # 统计被拦截的买入建议：v2.0 建议是建仓/加仓，但 v2.1A 被 override
            if use_odds_gate:
                raw_action_map = {a["code"]: a["advice"] for a in raw_advices}
                for adv in odds_only_advices:
                    raw_action = raw_action_map.get(adv["code"], "")
                    if raw_action in ("建仓", "加仓") and adv["advice"] != raw_action:
                        buys_blocked += 1

            if use_market_gate:
                raw_action_map = {a["code"]: a["advice"] for a in odds_only_advices}
                for adv in advices:
                    raw_action = raw_action_map.get(adv["code"], "")
                    if (
                        raw_action in ("建仓", "加仓")
                        and adv["advice"] != raw_action
                        and adv.get("signal_source") == "market_regime"
                    ):
                        market_blocked += 1

            # 根据 advice 更新模拟持仓 + 收集事件
            for adv in advices:
                code = adv["code"]
                action = adv["advice"]

                if action in ("观望", "不操作", "继续持有"):
                    continue

                exec_date_str = self.calendar.get_next_trading_day(adv["date"])
                if exec_date_str is None:
                    continue

                code_prices = price_map.get(code, {})
                exec_price = code_prices.get(exec_date_str)
                if exec_price is None:
                    continue

                exec_date = date.fromisoformat(exec_date_str)

                # 加仓冷却期
                if action in ("建仓", "加仓") and code in last_add_date:
                    days_since = (exec_date - last_add_date[code]).days
                    if days_since < self.cooldown_days:
                        continue

                # 收集事件 + 统计
                if code not in codes_events:
                    codes_events[code] = []
                codes_events[code].append(
                    (exec_date, action, exec_price, adv.get("signal_source", "trend"))
                )
                if action == "建仓":
                    buy_events += 1
                elif action == "加仓":
                    add_events += 1
                elif action == "卖出":
                    sell_events += 1

                # 更新模拟持仓
                if action == "建仓":
                    sim_positions[code] = {
                        "id": _pos_id,
                        "code": code,
                        "cost": exec_price,
                        "shares": _VIRTUAL_SHARES,
                        "entry_date": str(exec_date),
                    }
                    last_add_date[code] = exec_date
                    _pos_id += 1

                elif action == "加仓" and code in sim_positions:
                    pos = sim_positions[code]
                    total_cost = pos["cost"] * pos["shares"] + exec_price * _VIRTUAL_SHARES
                    pos["shares"] += _VIRTUAL_SHARES
                    pos["cost"] = total_cost / pos["shares"]
                    last_add_date[code] = exec_date

                elif action == "卖出" and code in sim_positions:
                    del sim_positions[code]
                    last_add_date.pop(code, None)

        # 运行交易引擎
        all_trades: list[VirtualTrade] = []
        for code, events in codes_events.items():
            events.sort(key=lambda x: x[0])
            code_prices = price_map.get(code, {})
            latest_price = max(code_prices.values()) if code_prices else None
            code_trades = _simulate_trade_engine(events, latest_price)
            for t in code_trades:
                t.code = code
            all_trades.extend(code_trades)

        # 构建权益曲线
        equity_curve = pd.DataFrame()
        if codes_events:
            all_exec_dates: list[date] = []
            for events in codes_events.values():
                for exec_date, _, _, _ in events:
                    all_exec_dates.append(exec_date)
            if all_exec_dates:
                curve_start = min(all_exec_dates)
                curve_end = max(all_exec_dates)
                trading_days = self.calendar.get_trading_days_in_range(curve_start, curve_end)
                equity_curve = _build_equity_curve_from_events(
                    codes_events, price_map, trading_days
                )

        # 统计已平仓/未平仓交易
        closed_count = sum(1 for t in all_trades if t.exit_date is not None)
        open_count = sum(1 for t in all_trades if t.exit_date is None)

        stats = {
            "buys_blocked": buys_blocked,
            "buy_events": buy_events,
            "add_events": add_events,
            "sell_events": sell_events,
            "open_positions": open_count,
            "closed_trades": closed_count,
            "market_blocked": market_blocked,
        }
        return all_trades, equity_curve, stats

    # ── 对比入口 ──

    def compare(
        self,
        codes: list[str],
        start: date,
        end: date,
    ) -> dict:
        """运行 v2.0 vs v2.1A 对比回测。

        Args:
            codes: ETF 代码列表
            start: 回测起始日期
            end:   回测结束日期

        Returns:
            {
                "v20": {"trades": [...], "summary": {...}, "equity_curve": DataFrame},
                "v21": {"trades": [...], "summary": {...}, "equity_curve": DataFrame,
                        "buys_blocked": int},
                "per_etf": [{"code": "588000",
                             "v20_summary": {...}, "v21_summary": {...},
                             "v20_trades": [...], "v21_trades": [...]}, ...],
                "meta": {"start": date, "end": date, "codes": [...], "cost_ratio": float},
            }
        """
        df, price_map, odds_map_full, market_regime_map = self.load_data(codes, start, end)

        if df.empty:
            empty_summary = get_summary([])
            return {
                "v20": {"trades": [], "summary": empty_summary, "equity_curve": pd.DataFrame()},
                "v21": {"trades": [], "summary": empty_summary, "equity_curve": pd.DataFrame(),
                        "buys_blocked": 0},
                "v22_market": {"trades": [], "summary": empty_summary,
                               "equity_curve": pd.DataFrame(),
                               "stats": {"market_blocked": 0}},
                "per_etf": [],
                "meta": {"start": start, "end": end, "codes": codes, "cost_ratio": 0.0},
            }

        logger.info(f"开始赔率门控回测: {len(codes)} 只 ETF, {start} ~ {end}")

        # ── V2.0（无门控）──
        logger.info("运行 V2.0（无赔率门控）...")
        v20_trades, v20_equity, v20_stats = self._simulate_version(
            df, price_map, odds_map_full, use_odds_gate=False
        )

        # ── V2.1A（有门控）──
        logger.info("运行 V2.1A（有赔率门控）...")
        v21_trades, v21_equity, v21_stats = self._simulate_version(
            df, price_map, odds_map_full, use_odds_gate=True
        )

        # ── V2.2（赔率门控 + 市场热度门控）──
        logger.info("运行 V2.2（赔率门控 + 市场热度门控）...")
        v22_trades, v22_equity, v22_stats = self._simulate_version(
            df,
            price_map,
            odds_map_full,
            use_odds_gate=True,
            use_market_gate=True,
            market_regime_map=market_regime_map,
        )

        # ── 交易成本估算 ──
        # 默认 万 0.5（ETF 佣金），在对比中统一扣除
        cost_ratio = 0.00005

        # ── 按 ETF 拆分对比 ──
        per_etf = []
        for code in codes:
            v20_code_trades = [t for t in v20_trades if t.code == code]
            v21_code_trades = [t for t in v21_trades if t.code == code]
            v22_code_trades = [t for t in v22_trades if t.code == code]

            # 扣除交易成本后的累计盈亏
            v20_summary_raw = get_summary(v20_code_trades)
            v21_summary_raw = get_summary(v21_code_trades)
            v22_summary_raw = get_summary(v22_code_trades)

            v20_trade_count = v20_summary_raw["total_trades"]
            v21_trade_count = v21_summary_raw["total_trades"]
            v22_trade_count = v22_summary_raw["total_trades"]

            v20_summary = dict(v20_summary_raw)
            v21_summary = dict(v21_summary_raw)
            v22_summary = dict(v22_summary_raw)

            # 每笔交易扣除双边成本（买+卖）
            v20_summary["cumulative_pnl_pct"] = round(
                v20_summary_raw["cumulative_pnl_pct"] - v20_trade_count * 2 * cost_ratio, 6
            )
            v21_summary["cumulative_pnl_pct"] = round(
                v21_summary_raw["cumulative_pnl_pct"] - v21_trade_count * 2 * cost_ratio, 6
            )
            v22_summary["cumulative_pnl_pct"] = round(
                v22_summary_raw["cumulative_pnl_pct"] - v22_trade_count * 2 * cost_ratio, 6
            )

            per_etf.append({
                "code": code,
                "v20_summary": v20_summary,
                "v21_summary": v21_summary,
                "v22_market_summary": v22_summary,
                "v20_trades": v20_code_trades,
                "v21_trades": v21_code_trades,
                "v22_market_trades": v22_code_trades,
            })

        # ── 全量汇总 ──
        v20_summary_all = get_summary(v20_trades)
        v21_summary_all = get_summary(v21_trades)
        v22_summary_all = get_summary(v22_trades)

        v20_total_trades = v20_summary_all["total_trades"]
        v21_total_trades = v21_summary_all["total_trades"]
        v22_total_trades = v22_summary_all["total_trades"]

        v20_summary_all["cumulative_pnl_pct"] = round(
            v20_summary_all["cumulative_pnl_pct"] - v20_total_trades * 2 * cost_ratio, 6
        )
        v21_summary_all["cumulative_pnl_pct"] = round(
            v21_summary_all["cumulative_pnl_pct"] - v21_total_trades * 2 * cost_ratio, 6
        )
        v22_summary_all["cumulative_pnl_pct"] = round(
            v22_summary_all["cumulative_pnl_pct"] - v22_total_trades * 2 * cost_ratio, 6
        )

        result = {
            "v20": {
                "trades": v20_trades,
                "summary": v20_summary_all,
                "equity_curve": v20_equity,
                "stats": v20_stats,
            },
            "v21": {
                "trades": v21_trades,
                "summary": v21_summary_all,
                "equity_curve": v21_equity,
                "stats": v21_stats,
            },
            "v22_market": {
                "trades": v22_trades,
                "summary": v22_summary_all,
                "equity_curve": v22_equity,
                "stats": v22_stats,
            },
            "per_etf": per_etf,
            "meta": {
                "start": start,
                "end": end,
                "codes": codes,
                "cost_ratio": cost_ratio,
            },
        }

        logger.info(
            f"回测完成: V2.0 trades={v20_total_trades}(closed) events="
            f"B{v20_stats['buy_events']}/A{v20_stats['add_events']}/"
            f"S{v20_stats['sell_events']}, "
            f"V2.1A trades={v21_total_trades}(closed) events="
            f"B{v21_stats['buy_events']}/A{v21_stats['add_events']}/"
            f"S{v21_stats['sell_events']}, "
            f"blocked={v21_stats['buys_blocked']}, "
            f"V2.2-market trades={v22_total_trades}(closed) events="
            f"B{v22_stats['buy_events']}/A{v22_stats['add_events']}/"
            f"S{v22_stats['sell_events']}, "
            f"market_blocked={v22_stats['market_blocked']}"
        )
        return result


# ── 便捷入口 ──

def run_odds_gate_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    cooldown_days: int = 5,
) -> dict:
    """一键运行赔率门控回测对比。

    Args:
        codes:         ETF 代码列表，None 使用 settings.yaml 中的全部 ETF
        start:         回测起始日期，None 时自动推算（最早信号日期）
        end:           回测结束日期，None 时使用昨天
        cooldown_days: 加仓冷却期（自然日）

    Returns:
        与 OddsGateBacktest.compare() 相同结构的 dict
    """
    config = load_config()
    calendar = TradingCalendarService()

    if codes is None:
        codes = [etf.symbol for etf in config.etf_list]

    if end is None:
        end = date.today() - timedelta(days=1)

    # 推算合理起始日期：取最早有信号的日期（最少往前看 3 年）
    # 注意：调用方须已初始化 engine
    if start is None:
        earliest = None
        for code in codes:
            sigs = signals_repo.find_by_code_between(code, None, end)
            if sigs:
                first_date = sigs[0].date
                if earliest is None or first_date < earliest:
                    earliest = first_date
        if earliest:
            start = earliest
        else:
            start = end - timedelta(days=365 * 3)

    engine = OddsGateBacktest(calendar, cooldown_days)
    return engine.compare(codes, start, end)


# ── 结果格式化工具 ──

def format_comparison_report(result: dict) -> str:
    """将回测对比结果格式化为 Markdown 文本报告。

    Args:
        result: OddsGateBacktest.compare() 的返回结果

    Returns:
        Markdown 格式的报告字符串
    """
    meta = result["meta"]
    v20 = result["v20"]
    v21 = result["v21"]
    v22 = result.get("v22_market")

    lines = [
        "# V2.0 vs V2.1A vs V2.2 市场热度门控回测报告",
        "",
        f"**回测区间**: {meta['start']} ~ {meta['end']}",
        f"**ETF 数量**: {len(meta['codes'])}",
        f"**交易成本**: {meta['cost_ratio']*10000:.1f}‱（双边）",
        "",
        "## 事件统计",
        "",
        "| 事件 | V2.0 (无门控) | V2.1A (赔率门控) | V2.2 (赔率+市场) |",
        "|------|-------------|-------------|-------------|",
    ]

    v20_stats = v20.get("stats", {})
    v21_stats = v21.get("stats", {})
    v22_stats = v22.get("stats", {}) if v22 else {}

    lines.append(
        f"| 建仓 | {v20_stats.get('buy_events', 0)} | "
        f"{v21_stats.get('buy_events', 0)} | {v22_stats.get('buy_events', 0)} |"
    )
    lines.append(
        f"| 加仓 | {v20_stats.get('add_events', 0)} | "
        f"{v21_stats.get('add_events', 0)} | {v22_stats.get('add_events', 0)} |"
    )
    lines.append(
        f"| 卖出 | {v20_stats.get('sell_events', 0)} | "
        f"{v21_stats.get('sell_events', 0)} | {v22_stats.get('sell_events', 0)} |"
    )
    lines.append(
        f"| 未平仓 | {v20_stats.get('open_positions', 0)} | "
        f"{v21_stats.get('open_positions', 0)} | {v22_stats.get('open_positions', 0)} |"
    )
    lines.append(
        f"| 赔率买入拦截 | — | {v21_stats.get('buys_blocked', 0)} | "
        f"{v22_stats.get('buys_blocked', 0)} |"
    )
    lines.append(
        f"| 市场热度拦截 | — | — | {v22_stats.get('market_blocked', 0)} |"
    )
    lines.append("")

    s20 = v20["summary"]
    s21 = v21["summary"]
    s22 = v22["summary"] if v22 else None

    # 如果已平仓交易为 0，提示窗口太短
    if s20.get("total_trades", 0) == 0 and s21.get("total_trades", 0) == 0:
        lines.append(
            "> ⚠ **已平仓交易数为 0**，回测窗口内没有完整的买入→卖出闭环。"
            "请使用 `--start` 参数扩展回测区间至 2 年以上以覆盖完整交易周期。"
        )
        lines.append("")

    lines.append("## 全量汇总（已平仓交易）")
    lines.append("")
    lines.append("| 指标 | V2.0 (无门控) | V2.1A (赔率门控) | V2.2 (赔率+市场) | V2.2 较 V2.1A |")
    lines.append("|------|-------------|-------------|-------------|------|")

    def _delta_str(v20_val: float, v21_val: float, fmt: str = ".2f",
                   inverse_good: bool = False) -> str:
        """计算变化值并标记方向。inverse_good=True 表示减少是好的（如回撤）。"""
        delta = v21_val - v20_val
        if abs(v20_val) < 1e-9:
            return "—" if abs(delta) < 1e-9 else f"{delta:+{fmt}}"
        pct = delta / abs(v20_val) * 100
        arrow = ""
        if delta > 0.001 and not inverse_good:
            arrow = " ▲"
        elif delta < -0.001 and not inverse_good:
            arrow = " ▼"
        elif delta > 0.001 and inverse_good:
            arrow = " ▼"
        elif delta < -0.001 and inverse_good:
            arrow = " ▲"
        return f"{delta:+{fmt}} ({pct:+.1f}%){arrow}"

    s20 = v20["summary"]
    s21 = v21["summary"]
    s22 = v22["summary"] if v22 else s21

    metrics = [
        ("交易次数", s20["total_trades"], s21["total_trades"], s22["total_trades"], ".0f", False),
        ("胜率", s20["win_rate"], s21["win_rate"], s22["win_rate"], ".1%", False),
        ("累计盈亏", s20["cumulative_pnl_pct"], s21["cumulative_pnl_pct"], s22["cumulative_pnl_pct"], ".4%", False),
        ("最大回撤", s20["max_drawdown"], s21["max_drawdown"], s22["max_drawdown"], ".4%", True),
        ("平均盈亏", s20["avg_pnl_pct"], s21["avg_pnl_pct"], s22["avg_pnl_pct"], ".4%", False),
        ("最大单笔盈利", s20["max_win"], s21["max_win"], s22["max_win"], ".4%", False),
        ("最大单笔亏损", s20["max_loss"], s21["max_loss"], s22["max_loss"], ".4%", True),
        ("平均持有天数", s20["avg_holding_days"], s21["avg_holding_days"], s22["avg_holding_days"], ".1f", False),
    ]

    for label, v20_val, v21_val, v22_val, fmt, inverse in metrics:
        if isinstance(v20_val, float) and fmt.endswith("%"):
            v20_str = f"{v20_val:{fmt}}"
            v21_str = f"{v21_val:{fmt}}"
            v22_str = f"{v22_val:{fmt}}"
        elif isinstance(v20_val, float):
            v20_str = f"{v20_val:{fmt}}"
            v21_str = f"{v21_val:{fmt}}"
            v22_str = f"{v22_val:{fmt}}"
        else:
            v20_str = f"{v20_val}"
            v21_str = f"{v21_val}"
            v22_str = f"{v22_val}"
        lines.append(
            f"| {label} | {v20_str} | {v21_str} | {v22_str} | "
            f"{_delta_str(float(v21_val), float(v22_val), fmt.replace('%',''), inverse)} |"
        )

    # 按 ETF 明细
    lines.append("")
    lines.append("## 按 ETF 明细")
    lines.append("")
    lines.append(
        "| ETF | V2.1A 交易数 | V2.2 交易数 | V2.1A 累计盈亏 | V2.2 累计盈亏 | "
        "V2.1A 胜率 | V2.2 胜率 | V2.1A 最大回撤 | V2.2 最大回撤 |"
    )
    lines.append(
        "|-----|-----------|-----------|------------|------------|"
        "---------|---------|------------|------------|"
    )

    for etf in result.get("per_etf", []):
        v21s = etf["v21_summary"]
        v22s = etf.get("v22_market_summary", v21s)
        lines.append(
            f"| {etf['code']} | {v21s['total_trades']} | {v22s['total_trades']} | "
            f"{v21s['cumulative_pnl_pct']:+.4%} | {v22s['cumulative_pnl_pct']:+.4%} | "
            f"{v21s['win_rate']:.1%} | {v22s['win_rate']:.1%} | "
            f"{v21s['max_drawdown']:.4%} | {v22s['max_drawdown']:.4%} |"
        )

    return "\n".join(lines)
