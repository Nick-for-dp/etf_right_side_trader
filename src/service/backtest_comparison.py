"""策略回测对比：旧均线策略 vs 当前多指标策略。

纯内存计算，不修改数据库。复用 profit_analysis_service 的 _simulate_trade_engine
状态机 + advisor 的 generate_advice 查表，确保与生产环境交易模拟口径一致。
"""

from datetime import date, timedelta

import pandas as pd

from src.advisor import generate_advice
from src.database import indicators_repo, quote_repo
from src.models import VirtualTrade
from src.service.profit_analysis_service import _simulate_trade_engine, get_summary
from src.service.calendar_service import TradingCalendarService


# ── 辅助：从多代码事件 + 价格映射构建权益曲线 ──

def _build_equity_curve_from_events(
    codes_events: dict[str, list[tuple[date, str, float, str]]],
    price_map: dict[str, dict[str, float]],
    trading_days: list[str],
) -> pd.DataFrame:
    """从多 ETF 交易事件重建逐日权益曲线（纯函数，无 DB 依赖）。

    Args:
        codes_events: {code: [(exec_date, action, exec_price, signal_source), ...]}
        price_map:     {code: {date_str: close}}
        trading_days:  排序后的交易日列表

    Returns:
        DataFrame，列 = [date, realized, unrealized, equity]，与 calculate_equity_curve 一致
    """
    # 拉平为全局时间线 [(exec_date, code, action, price), ...]
    timeline: list[tuple[date, str, str, float]] = []
    for code, events in codes_events.items():
        for exec_date, action, exec_price, _signal_source in events:
            timeline.append((exec_date, code, action, exec_price))
    timeline.sort(key=lambda x: x[0])

    active_positions: dict[str, dict] = {}  # {code: {avg_cost, units}}
    realized_pnl = 0.0
    rows = []

    for td_str in trading_days:
        td = date.fromisoformat(td_str)

        # 处理当日到期的事件
        for exec_date, code, action, price in timeline:
            if exec_date != td:
                continue

            if action in ("建仓", "加仓"):
                if code not in active_positions:
                    active_positions[code] = {"avg_cost": price, "units": 1}
                else:
                    pos = active_positions[code]
                    total_units = pos["units"] + 1
                    total_cost = pos["avg_cost"] * pos["units"] + price
                    pos["avg_cost"] = total_cost / total_units
                    pos["units"] = total_units

            elif action == "卖出" and code in active_positions:
                pos = active_positions[code]
                trade_pnl = (price - pos["avg_cost"]) / pos["avg_cost"]
                realized_pnl += trade_pnl
                del active_positions[code]

        # 当日浮动盈亏
        unrealized_pnl = 0.0
        for code, pos in active_positions.items():
            close_price = price_map.get(code, {}).get(td_str)
            if close_price is not None:
                unrealized_pnl += (close_price - pos["avg_cost"]) / pos["avg_cost"]

        rows.append({
            "date": td,
            "realized": round(realized_pnl, 6),
            "unrealized": round(unrealized_pnl, 6),
            "equity": round(1.0 + realized_pnl + unrealized_pnl, 6),
        })

    return pd.DataFrame(rows)


# ── 核心类 ──

class BacktestComparison:
    """双策略回测对比引擎。

    加载指标 + 行情数据 → 分别运行 v1.2 / v2.0 策略 → 模拟交易 → 输出对比结果。
    两个策略摄入完全相同的 DataFrame，确保公平对比。
    """

    def __init__(self, calendar: TradingCalendarService, cooldown_days: int = 5):
        self.calendar = calendar
        self.cooldown_days = cooldown_days  # 建仓/加仓后的冷却期（自然日）

    # ── 数据加载 ──

    def load_data(
        self, codes: list[str], start: date, end: date
    ) -> tuple[pd.DataFrame, dict[str, dict[str, float]], list[str]]:
        """从 indicators + quote 表加载数据，组装策略可消费的 DataFrame。

        Args:
            codes: ETF 代码列表
            start: 起始日期
            end:   结束日期

        Returns:
            (df, price_map, trading_days):
            - df:            columns = [code, date, ma20, ma60, close, dif, dea, rsi,
                              bb_mid, bb_upper, bb_lower, bb_width, adx14, vol_ratio]
            - price_map:     {code: {date_str: close}}，用于成交价查找
            - trading_days:  区间内排序后的交易日列表，用于权益曲线
        """
        # 扩大查询范围以覆盖指标窗口期
        fetch_start = start - timedelta(days=120)

        rows = []
        price_map: dict[str, dict[str, float]] = {}

        for code in codes:
            # 指标数据
            indicators = indicators_repo.find_by_code_between(code, fetch_start, end)
            ind_by_date: dict[str, dict] = {}
            for ind in indicators:
                ind_by_date[str(ind.date)] = ind.data

            # 行情数据（用于 close + 成交价映射）
            quotes = quote_repo.find_by_code_in_range(code, fetch_start, end)
            code_prices: dict[str, float] = {}
            for q in quotes:
                d_str = str(q.date)
                code_prices[d_str] = float(q.close)
            price_map[code] = code_prices

            # 组装行：指标 + close join
            for d_str, ind_data in ind_by_date.items():
                close = code_prices.get(d_str)
                if close is None:
                    continue  # 有指标无行情 → 跳过（无法做归一化）
                row = {
                    "code": code,
                    "date": d_str,
                    "close": close,
                }
                # 提取策略所需指标列
                for col in [
                    "ma20", "ma60", "dif", "dea", "rsi",
                    "bb_mid", "bb_upper", "bb_lower", "bb_width",
                    "adx14", "vol_ratio",
                ]:
                    row[col] = ind_data.get(col)
                rows.append(row)

        if rows:
            df = pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)
        else:
            df = pd.DataFrame(columns=[
                "code", "date", "close", "ma20", "ma60", "dif", "dea", "rsi",
                "bb_mid", "bb_upper", "bb_lower", "bb_width", "adx14", "vol_ratio",
            ])

        # 交易日列表
        trading_days = self.calendar.get_trading_days_in_range(start, end)

        return df, price_map, trading_days

    # ── 单策略运行 ──

    def run_strategy(
        self,
        strategy,
        df: pd.DataFrame,
        price_map: dict[str, dict[str, float]],
    ) -> tuple[list[VirtualTrade], pd.DataFrame]:
        """用指定策略生成信号 → advisor 转建议 → 模拟交易。

        逐日推进信号日期，维护模拟持仓状态传给 advisor，使其能正确映射
        BUY→建仓/加仓、SELL→卖出，而非死板地返回"不操作"。

        Args:
            strategy:   BaseStrategy 实例（v1.2 或 v2.0）
            df:         load_data 返回的指标 DataFrame
            price_map:  {code: {date_str: close}}

        Returns:
            (trades, equity_curve):
            - trades:       所有代码的 VirtualTrade 列表（code 已填充）
            - equity_curve: 多代码合并的权益曲线 DataFrame
        """
        # 第一步：策略生成信号
        signal_df = strategy.generate(df)

        if signal_df.empty:
            return [], pd.DataFrame()

        # 第二步：按日期排序，逐日推进信号 + 维护模拟持仓 → advisor
        signal_df = signal_df.sort_values(["date", "code"]).reset_index(drop=True)

        # 模拟持仓状态：{code: {id, code, cost, shares, entry_date}}
        sim_positions: dict[str, dict] = {}
        # 加仓冷却期追踪：{code: 上次加仓/建仓的执行日期}
        last_add_date: dict[str, date] = {}
        _sim_pos_id_counter = 1

        # 收集所有代码的交易事件，按代码分组
        codes_events: dict[str, list[tuple[date, str, float, str]]] = {}

        # 逐日处理信号
        for signal_date in signal_df["date"].unique():
            day_signals = signal_df[signal_df["date"] == signal_date]

            # 当前持仓列表
            pos_list = list(sim_positions.values())

            # 调用 advisor：传入当前模拟持仓，使其能正确映射 SELL→卖出
            advices = generate_advice(
                positions=pos_list,
                signals=day_signals,
                current_prices={},
                risk_signals={},
            )

            # 根据 advice 更新模拟持仓 + 收集事件
            for adv in advices:
                code = adv["code"]
                action = adv["advice"]

                # 跳过无操作的建议
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
                signal_source = adv.get("signal_source", "trend")

                # ── 加仓冷却期检查（真实交易不会每日加仓）──
                if action in ("建仓", "加仓") and code in last_add_date:
                    days_since = (exec_date - last_add_date[code]).days
                    if days_since < self.cooldown_days:
                        continue  # 冷却期内，跳过本次加仓

                # 收集事件（用于 _simulate_trade_engine 和权益曲线）
                if code not in codes_events:
                    codes_events[code] = []
                codes_events[code].append(
                    (exec_date, action, exec_price, signal_source)
                )

                # ── 更新模拟持仓 ──
                if action == "建仓":
                    # 新建持仓（若已有同代码持仓则先清掉，模拟引擎会结算旧仓）
                    sim_positions[code] = {
                        "id": _sim_pos_id_counter,
                        "code": code,
                        "cost": exec_price,
                        "shares": 1000,  # shares 仅用于 advisor 判断 has_pos，值不重要
                        "entry_date": str(exec_date),
                    }
                    last_add_date[code] = exec_date
                    _sim_pos_id_counter += 1

                elif action == "加仓" and code in sim_positions:
                    # 均价重算
                    pos = sim_positions[code]
                    total_cost = pos["cost"] * pos["shares"] + exec_price * 1000
                    pos["shares"] += 1000
                    pos["cost"] = total_cost / pos["shares"]
                    last_add_date[code] = exec_date

                elif action == "卖出" and code in sim_positions:
                    del sim_positions[code]
                    # 卖出后重置冷却期，允许后续重新入场
                    last_add_date.pop(code, None)

        # 第三步：逐代码运行 _simulate_trade_engine
        all_trades: list[VirtualTrade] = []
        for code, events in codes_events.items():
            events.sort(key=lambda x: x[0])

            # 最新收盘价（用于未平仓浮动盈亏）
            code_prices = price_map.get(code, {})
            latest_price = None
            if code_prices:
                latest_date = max(code_prices.keys())
                latest_price = code_prices[latest_date]

            code_trades = _simulate_trade_engine(events, latest_price)
            for t in code_trades:
                t.code = code
            all_trades.extend(code_trades)

        # 第四步：构建多代码合并的权益曲线
        if not codes_events:
            return all_trades, pd.DataFrame()

        all_dates: list[date] = []
        for events in codes_events.values():
            for exec_date, _, _, _ in events:
                all_dates.append(exec_date)
        if not all_dates:
            return all_trades, pd.DataFrame()

        curve_start = min(all_dates)
        curve_end = max(all_dates)
        trading_days = self.calendar.get_trading_days_in_range(curve_start, curve_end)
        equity_curve = _build_equity_curve_from_events(
            codes_events, price_map, trading_days
        )

        return all_trades, equity_curve

    # ── 对比入口 ──

    def compare(
        self,
        v1_strategy,
        v2_strategy,
        codes: list[str],
        start: date,
        end: date,
    ) -> dict:
        """运行双策略对比，返回结构化结果。

        Args:
            v1_strategy: v1.2 策略实例
            v2_strategy: v2.0 策略实例
            codes:       要对比的 ETF 代码列表
            start:       回测起始日期
            end:         回测结束日期

        Returns:
            {
                "v1": {"trades": [...], "summary": {...}, "equity_curve": DataFrame},
                "v2": {"trades": [...], "summary": {...}, "equity_curve": DataFrame},
                "meta": {"start": date, "end": date, "codes": [...], "trading_days": [...]},
            }
        """
        df, price_map, trading_days = self.load_data(codes, start, end)

        if df.empty:
            return {
                "v1": {"trades": [], "summary": get_summary([]), "equity_curve": pd.DataFrame()},
                "v2": {"trades": [], "summary": get_summary([]), "equity_curve": pd.DataFrame()},
                "meta": {"start": start, "end": end, "codes": codes, "trading_days": trading_days},
            }

        v1_trades, v1_equity = self.run_strategy(v1_strategy, df, price_map)
        v2_trades, v2_equity = self.run_strategy(v2_strategy, df, price_map)

        return {
            "v1": {
                "trades": v1_trades,
                "summary": get_summary(v1_trades),
                "equity_curve": v1_equity,
            },
            "v2": {
                "trades": v2_trades,
                "summary": get_summary(v2_trades),
                "equity_curve": v2_equity,
            },
            "meta": {
                "start": start,
                "end": end,
                "codes": codes,
                "trading_days": trading_days,
            },
        }
