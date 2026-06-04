"""真实账户净值口径回测引擎。

每日跟踪 cash + positions × close = total_equity，
支持多 ETF 同时持仓、资金约束、交易成本和版本对比。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.advisor import generate_advice
from src.database import indicators_repo, market_regime_repo, quote_repo, signals_repo
from src.models import MarketState, SignalType
from src.service.calendar_service import TradingCalendarService
from src.utils import get_logger

logger = get_logger(__name__)


# ── 数据结构 ──


@dataclass
class Position:
    """单个持仓。"""
    code: str
    shares: float = 0.0
    cost: float = 0.0          # 持仓总成本（元）
    entry_date: date | None = None

    @property
    def avg_cost(self) -> float:
        return self.cost / self.shares if self.shares > 0 else 0.0


@dataclass
class PortfolioState:
    """组合状态快照。"""
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    @property
    def total_equity(self) -> float:
        return self.cash + self.market_value

    @property
    def market_value(self) -> float:
        return sum(p.cost for p in self.positions.values()) if self.positions else 0.0

    def market_value_at(self, prices: dict[str, float]) -> float:
        return sum(
            pos.shares * prices.get(pos.code, pos.avg_cost)
            for pos in self.positions.values()
        )

    def total_equity_at(self, prices: dict[str, float]) -> float:
        return self.cash + self.market_value_at(prices)


@dataclass
class TradeLog:
    """单笔成交记录。"""
    code: str
    date: date
    action: str          # "BUY" / "SELL"
    price: float
    shares: float
    cost: float          # 佣金 + 滑点
    cash_before: float
    cash_after: float
    version: str


@dataclass
class EquityPoint:
    """每日净值点。"""
    date: date
    cash: float
    market_value: float
    total_equity: float
    version: str


# ── 回测引擎 ──


class PortfolioBacktest:
    """真实账户净值口径回测引擎。

    使用与生产一致的 signals 表数据，通过 generate_advice 生成操作建议，
    在共享现金池约束下执行买卖，输出每日权益曲线和业绩指标。

    Args:
        calendar: 交易日历服务
        initial_capital: 初始资金（元）
        cost_ratio: 佣金率（如 0.0005 = 万分之五）
        slippage: 滑点率（如 0.0001 = 万分之一）
        position_limit: 单 ETF 仓位上限（占净资产比例，如 0.3 = 30%）
        cooldown_days: 加仓冷却天数
    """

    def __init__(
        self,
        calendar: TradingCalendarService,
        initial_capital: float = 100_000.0,
        cost_ratio: float = 0.0005,
        slippage: float = 0.0001,
        position_limit: float = 0.3,
        cooldown_days: int = 5,
    ):
        self.calendar = calendar
        self.initial_capital = initial_capital
        self.cost_ratio = cost_ratio
        self.slippage = slippage
        self.position_limit = position_limit
        self.cooldown_days = cooldown_days

    # ── 数据加载 ──

    def load_data(
        self, codes: list[str], start: date, end: date
    ) -> tuple[
        dict[str, pd.DataFrame],                # {version: signals_df}
        dict[str, dict[str, float]],            # {code: {date_str: close}}
        dict[str, dict[str, dict]],             # {code: {date_str: odds_info}}
        dict[str, dict],                        # {date_str: regime_info}
        list[str],                              # 全部交易日
    ]:
        """加载回测所需数据，支持多策略版本。

        Returns:
            signals_by_version: {version: DataFrame[code, date, signal, signal_meta]}
            price_map:          {code: {date_str: close}}
            odds_map_full:      {code: {date_str: {odds_state, odds_score, premium_blocked}}}
            market_regime_map:  {date_str: {state, score, data}}
            trading_days:       全部交易日列表
        """
        fetch_start = start - timedelta(days=120)
        price_map: dict[str, dict[str, float]] = {}
        odds_map_full: dict[str, dict[str, dict]] = {}

        for code in codes:
            # 行情
            quotes = quote_repo.find_by_code_in_range(code, fetch_start, end)
            code_prices: dict[str, float] = {}
            for q in quotes:
                code_prices[str(q.date)] = float(q.close)
            price_map[code] = code_prices

            # 赔率
            indicators = indicators_repo.find_by_code_between(code, fetch_start, end)
            code_odds: dict[str, dict] = {}
            for ind in indicators:
                d_str = str(ind.date)
                odds_state = ind.data.get("odds_state")
                if odds_state is not None:
                    code_odds[d_str] = {
                        "odds_state": odds_state,
                        "odds_score": ind.data.get("odds_score"),
                        "premium_blocked": ind.data.get("odds_premium_blocked", False),
                    }
            odds_map_full[code] = code_odds

        # 信号：按策略版本分组
        all_versions = set()
        for code in codes:
            sigs = signals_repo.find_by_code_between(code, start, end)
            for s in sigs:
                all_versions.add(s.strategy_version)

        signals_by_version: dict[str, list[dict]] = {v: [] for v in all_versions}
        for code in codes:
            sigs = signals_repo.find_by_code_between(code, start, end)
            for s in sigs:
                v = s.strategy_version
                close = price_map.get(code, {}).get(str(s.date))
                if close is None:
                    continue
                signals_by_version[v].append({
                    "code": code,
                    "date": str(s.date),
                    "close": close,
                    "signal": s.signal,
                    "signal_meta": s.signal_meta or {},
                })

        signals_df_by_version = {}
        for v, rows in signals_by_version.items():
            signals_df_by_version[v] = (
                pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)
            )

        # 市场热度
        regimes = market_regime_repo.find_between(start, end)
        market_regime_map = {
            str(r.date): {"state": r.state, "score": r.score, "data": r.data}
            for r in regimes
        }

        # 全部交易日
        trading_days = self.calendar.get_trading_days_in_range(start, end)

        return price_map, odds_map_full, market_regime_map, trading_days

    # ── 主入口 ──

    def run(
        self,
        codes: list[str],
        start: date,
        end: date,
    ) -> dict[str, Any]:
        """运行回测，同一份信号走三种 advisor 配置，返回各版本结果。

        三个版本：v2.3-tech-only（无门控）、v2.3-odds（赔率门控）、
        v2.3-full-gate（赔率 + 市场门控）
        """
        price_map, odds_map_full, market_regime_map, trading_days = \
            self.load_data(codes, start, end)
        trading_day_set = set(trading_days)

        signal_df = self._load_unified_signals(codes, start, end)
        if signal_df.empty:
            return {"meta": {"start": str(start), "end": str(end), "codes": codes,
                            "capital": self.initial_capital, "cost_ratio": self.cost_ratio,
                            "slippage": self.slippage, "position_limit": self.position_limit},
                    "versions": {}}

        versions_config = [
            ("v2.3-tech-only", False, False),
            ("v2.3-odds", True, False),
            ("v2.3-full-gate", True, True),
        ]

        result = {}
        for v_name, use_odds, use_market in versions_config:
            logger.info(f"回测 {v_name}: {len(signal_df)} 条信号, {len(codes)} 只 ETF")
            equity_curve, trades, stats = self._run_advisor_config(
                v_name, signal_df, codes, price_map,
                odds_map_full if use_odds else None,
                market_regime_map if use_market else None,
                trading_days,
                trading_day_set,
            )
            summary = self._compute_summary(equity_curve, trades, v_name)
            result[v_name] = {
                "equity_curve": equity_curve,
                "trades": trades,
                "summary": summary,
                "stats": stats,
            }

        return {
            "meta": {"start": str(start), "end": str(end), "codes": codes,
                     "capital": self.initial_capital, "cost_ratio": self.cost_ratio,
                     "slippage": self.slippage, "position_limit": self.position_limit},
            "versions": result,
        }

    def _load_unified_signals(self, codes: list[str], start: date, end: date) -> pd.DataFrame:
        """从 signals 表加载统一的信号 DataFrame。"""
        rows = []
        for code in codes:
            sigs = signals_repo.find_by_code_between(code, start, end)
            for s in sigs:
                rows.append({
                    "code": code, "date": str(s.date),
                    "signal": s.signal, "signal_meta": s.signal_meta or {},
                })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)

    # ── 单版本回测 ──

    def _run_advisor_config(
        self,
        version: str,
        signal_df: pd.DataFrame,
        codes: list[str],
        price_map: dict[str, dict[str, float]],
        odds_map: dict[str, dict[str, dict]] | None,
        market_regime_map: dict[str, dict] | None,
        trading_days: list[str],
        trading_day_set: set[str],
    ) -> tuple[list[EquityPoint], list[TradeLog], dict]:
        """单配置回测：逐日推进，资金约束下执行。"""
        portfolio = PortfolioState(cash=self.initial_capital)
        equity_curve: list[EquityPoint] = []
        trades: list[TradeLog] = []
        stats = {"buys_blocked": 0, "market_blocked": 0}
        pending_advices: dict[str, list[dict]] = {}

        # 按日期分组信号
        sig_by_date: dict[str, list[dict]] = {}
        for _, row in signal_df.iterrows():
            d = row["date"]
            if d not in sig_by_date:
                sig_by_date[d] = []
            sig_by_date[d].append(row.to_dict())

        # 逐日推进。trading_days 必须保持时间升序，不能转为 set 后遍历。
        for day_str in trading_days:
            day_date = date.fromisoformat(day_str)
            day_sigs = sig_by_date.get(day_str, [])

            current_prices = {
                code: price
                for code in codes
                if (price := price_map.get(code, {}).get(day_str)) is not None
            }

            # 先执行前一交易日生成、计划在今日成交的建议。
            for adv in pending_advices.pop(day_str, []):
                code = adv["code"]
                exec_price = current_prices.get(code)
                if exec_price is None:
                    continue
                self._execute_advice(
                    portfolio, code, adv["advice"], exec_price,
                    day_date, version, trades, current_prices,
                )

            # 记录今日收盘净值。
            mv = portfolio.market_value_at(current_prices)
            equity_curve.append(EquityPoint(
                date=day_date, cash=portfolio.cash,
                market_value=mv, total_equity=portfolio.cash + mv,
                version=version,
            ))

            # T+1 执行：获取下一交易日。超出回测范围则只记录净值，不再生成交易。
            exec_day_str = self.calendar.get_next_trading_day(day_str)
            if exec_day_str is None or exec_day_str not in trading_day_set:
                continue

            # 1) 处理风控：检查已有持仓是否需要止损/止盈
            risk_signals = self._check_risk(portfolio, price_map, day_str)

            # 2) 构建 positions 列表供 advisor
            pos_list = []
            for code, pos in portfolio.positions.items():
                pos_list.append({
                    "id": hash(code),
                    "code": code,
                    "cost": pos.avg_cost,
                    "shares": pos.shares,
                    "entry_date": pos.entry_date or day_date,
                })

            # 3) 生成操作建议
            regime = market_regime_map.get(day_str, {"state": "UNKNOWN"}) if market_regime_map else None
            last_buy_dates = self._get_last_buy_dates(trades, codes)
            day_odds_map = None
            if odds_map is not None:
                day_odds_map = {
                    code: odds_map.get(code, {}).get(day_str, {})
                    for code in codes
                }

            if day_sigs or risk_signals:
                signal_codes = {row["code"] for row in day_sigs}
                missing_risk_codes = set(risk_signals) - signal_codes
                if missing_risk_codes:
                    day_sigs = list(day_sigs) + [
                        {
                            "code": code,
                            "date": day_str,
                            "signal": SignalType.HOLD.value,
                            "signal_meta": {},
                        }
                        for code in missing_risk_codes
                    ]
                sig_frame = pd.DataFrame(day_sigs)
                advices = generate_advice(
                    positions=pos_list,
                    signals=sig_frame,
                    current_prices=current_prices,
                    risk_signals=risk_signals,
                    odds_map=day_odds_map,
                    market_regime=regime,
                    last_buy_dates=last_buy_dates,
                    add_cooldown_days=self.cooldown_days,
                )
            else:
                advices = []

            # 5) 统计拦截
            for adv in advices:
                if adv["advice"] in ("观望", "继续持有") and adv.get("signal_source") == "market_regime":
                    stats["market_blocked"] += 1

            # 6) 缓存操作建议，下一交易日按收盘价模拟成交。
            executable = [
                adv for adv in advices
                if adv["advice"] in ("建仓", "加仓", "卖出")
            ]
            if executable:
                pending_advices.setdefault(exec_day_str, []).extend(executable)

        return equity_curve, trades, stats

    # ── 执行单笔建议 ──

    def _execute_advice(
        self,
        portfolio: PortfolioState,
        code: str,
        advice_action: str,
        exec_price: float,
        exec_date: date,
        version: str,
        trades: list[TradeLog],
        market_prices: dict[str, float],
    ) -> None:
        """在资金约束下执行一条操作建议。"""
        pos = portfolio.positions.get(code)
        price_with_cost = exec_price * (1 + self.slippage)

        if advice_action in ("建仓", "加仓"):
            # 计算可用资金和仓位上限
            max_pos_value = portfolio.total_equity_at(market_prices) * self.position_limit
            current_pos_value = pos.shares * exec_price if pos else 0.0
            remaining = max_pos_value - current_pos_value
            affordable = portfolio.cash - remaining * self.cost_ratio  # 预留佣金

            if affordable <= 0 or remaining <= 0:
                return  # 超限或现金不足

            buy_value = min(remaining, affordable, portfolio.cash * 0.95)
            if buy_value < price_with_cost * 100:  # 至少买 100 股
                return

            shares = int(buy_value / price_with_cost / 100) * 100  # 整手
            if shares <= 0:
                return

            cost_total = shares * price_with_cost
            commission = cost_total * self.cost_ratio
            total_cost = cost_total + commission

            if total_cost > portfolio.cash:
                return

            cash_before = portfolio.cash
            portfolio.cash -= total_cost

            if pos:
                pos.shares += shares
                pos.cost += cost_total
            else:
                portfolio.positions[code] = Position(
                    code=code, shares=shares,
                    cost=cost_total, entry_date=exec_date,
                )

            trades.append(TradeLog(
                code=code, date=exec_date,
                action=advice_action, price=exec_price,
                shares=shares, cost=commission,
                cash_before=cash_before,
                cash_after=portfolio.cash,
                version=version,
            ))

        elif advice_action == "卖出" and pos and pos.shares > 0:
            cash_before = portfolio.cash
            sale_value = pos.shares * exec_price * (1 - self.slippage)
            commission = sale_value * self.cost_ratio
            portfolio.cash += sale_value - commission
            trades.append(TradeLog(
                code=code, date=exec_date,
                action="SELL", price=exec_price,
                shares=pos.shares, cost=commission,
                cash_before=cash_before,
                cash_after=portfolio.cash,
                version=version,
            ))
            del portfolio.positions[code]

    # ── 风控检查 ──

    def _check_risk(
        self,
        portfolio: PortfolioState,
        price_map: dict[str, dict[str, float]],
        day_str: str,
    ) -> dict[str, dict]:
        """检查持仓是否需要止损/止盈。

        简化版：持仓超过 8% 亏损直接触发卖出。
        """
        risk_signals: dict[str, dict] = {}
        for code, pos in portfolio.positions.items():
            close = price_map.get(code, {}).get(day_str)
            if close is None:
                continue
            pnl_pct = (close - pos.avg_cost) / pos.avg_cost
            if pnl_pct <= -0.08:
                risk_signals[code] = {"signal": "SELL", "source": "stop_loss"}
        return risk_signals

    # ── 辅助 ──

    def _get_last_buy_dates(
        self,
        trades: list[TradeLog],
        codes: list[str],
    ) -> dict[str, date]:
        """从交易记录中提取各 ETF 最近买入日期。"""
        last: dict[str, date] = {}
        for t in reversed(trades):
            if t.action in ("BUY", "建仓", "加仓") and t.code not in last:
                last[t.code] = t.date
        for code in codes:
            if code not in last:
                last[code] = date.min
        return last

    # ── 指标计算 ──

    def _compute_summary(
        self,
        equity_curve: list[EquityPoint],
        trades: list[TradeLog],
        version: str,
    ) -> dict[str, Any]:
        """计算回测业绩指标。"""
        if not equity_curve:
            return {"error": "no_equity_data"}

        from src.backtest.portfolio_metrics import calculate_metrics
        return calculate_metrics(equity_curve, trades, self.initial_capital)


def run_portfolio_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """便捷入口：加载配置 + 运行净值回测。

    Args:
        codes: ETF 代码列表，None 时覆盖配置中全部
        start: 回测起始日期，None 时按 lookback_days 推算
        end:   回测结束日期，None 时为昨天
        capital: 初始资金
        cost_ratio: 佣金率
        slippage: 滑点率
        position_limit: 单 ETF 仓位上限

    Returns:
        run() 的完整返回结果
    """
    from src.config import load_config
    config = load_config()

    if codes is None:
        codes = [e.symbol for e in config.etf_list]

    calendar = TradingCalendarService()

    if end is None:
        end_str = calendar.get_previous_trading_day()
        end = date.fromisoformat(end_str)
    if start is None:
        lookback = config.lookback_days
        start = end - timedelta(days=lookback)

    bt = PortfolioBacktest(
        calendar=calendar,
        initial_capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        cooldown_days=config.strategy_params.get("cooldown_days", 5),
    )
    return bt.run(codes, start, end)


def format_portfolio_report(result: dict[str, Any]) -> str:
    """格式化为可读的回测报告。"""
    lines = []
    lines.append("=" * 72)
    lines.append("  组合净值回测报告")
    lines.append("=" * 72)
    meta = result["meta"]
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  回测区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("")

    headers = ["版本", "年化收益", "最大回撤", "Calmar", "Sharpe",
               "胜率", "利润因子", "交易次数", "换手率"]
    cols = [18, 10, 10, 8, 8, 8, 10, 10, 8]
    sep = "  ".join("-" * c for c in cols)

    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + sep)

    version_order = ["v2.3-tech-only", "v2.3-odds", "v2.3-full-gate"]
    ordered_names = [
        *[name for name in version_order if name in result["versions"]],
        *[name for name in result["versions"] if name not in version_order],
    ]
    for v_name in ordered_names:
        v = result["versions"][v_name]
        s = v["summary"]
        label = {
            "v2.3-tech-only": "v2.3 技术信号",
            "v2.3-odds": "v2.3 赔率门控",
            "v2.3-full-gate": "v2.3 全门控",
        }.get(v_name, v_name)
        lines.append(
            f"  {label:18s}"
            f" {s.get('annual_return', 'N/A'):>8s}"
            f" {s.get('max_drawdown', 'N/A'):>8s}"
            f" {s.get('calmar', 'N/A'):>6s}"
            f" {s.get('sharpe', 'N/A'):>6s}"
            f" {s.get('win_rate', 'N/A'):>6s}"
            f" {s.get('profit_factor', 'N/A'):>8s}"
            f" {s.get('total_trades', 'N/A'):>8s}"
            f" {s.get('turnover', 'N/A'):>6s}"
        )
    lines.append("")

    return "\n".join(lines)
