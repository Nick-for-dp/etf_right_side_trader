"""生产唯一的组合净值回测引擎。

每日 cash + Σ(shares × close) = total_equity，T+1 收盘价成交，
共享现金池，单 ETF 仓位上限，佣金 + 滑点。

规则全部来自生产：settings.yaml 的 70/15/15 加仓预算、high_vol 质量分层
预算、profile 止损、90 日最大持有、加仓冷却、分市场状态门控。
信号从库内 signals 表读取，与实盘完全同源。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.advisor import generate_advice
from src.database import indicators_repo, market_regime_repo, quote_repo, signals_repo
from src.models import AdviceAction, MarketState, SignalType
from src.risk import RiskController
from src.service.calendar_service import TradingCalendarService
from src.service.market_regime_service import build_per_code_market_regime
from src.utils import get_logger

logger = get_logger(__name__)

VERSION = "v2.5 limited"

# high_vol 质量分层预算：score ≥ 65 满额，≥ 55 打 8 折，其余 6 折
QUALITY_STRONG_SCORE = 65.0
QUALITY_MEDIUM_SCORE = 55.0
QUALITY_STRONG_MULTIPLIER = 1.0
QUALITY_MEDIUM_MULTIPLIER = 0.8
QUALITY_WEAK_MULTIPLIER = 0.6


@dataclass
class Position:
    """回测持仓。"""
    code: str
    shares: float = 0.0
    cost: float = 0.0              # 持仓总成本（元）
    entry_date: date | None = None  # 首次建仓日，用于最大持有天数
    last_add_date: date | None = None
    target_budget: float = 0.0
    used_budget: float = 0.0
    add_count: int = 0

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
    action: str          # "建仓" / "加仓" / "SELL"
    price: float
    shares: float
    cost: float          # 佣金
    cash_before: float
    cash_after: float
    version: str
    signal_source: str | None = None
    reason: str | None = None


@dataclass
class EquityPoint:
    """每日净值点。"""
    date: date
    cash: float
    market_value: float
    total_equity: float
    version: str


class PortfolioBacktest:
    """组合净值回测引擎。

    Args:
        calendar: 交易日历服务
        initial_capital: 初始资金（元）
        cost_ratio: 佣金率
        slippage: 滑点率
        position_limit: 单 ETF 仓位上限（占净资产比例）
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
        market_regime_params: dict | None = None,
        code_regime_groups: dict[str, str] | None = None,
        code_stop_loss_profiles: dict[str, str] | None = None,
        code_volatility_groups: dict[str, str] | None = None,
        entry_add_budget: dict | None = None,
        risk_controller: RiskController | None = None,
    ):
        self.calendar = calendar
        self.initial_capital = initial_capital
        self.cost_ratio = cost_ratio
        self.slippage = slippage
        self.position_limit = position_limit
        self.cooldown_days = cooldown_days
        self.market_regime_params = market_regime_params or {}
        self.code_regime_groups = code_regime_groups or {}
        self.code_stop_loss_profiles = code_stop_loss_profiles or {}
        self.code_volatility_groups = code_volatility_groups or {}
        self.entry_add_budget = entry_add_budget or {}
        if risk_controller is None:
            from src.config import load_config
            risk_controller = RiskController(load_config())
        self.risk = risk_controller

    # ── 数据加载 ──

    def load_data(self, codes: list[str], start: date, end: date) -> tuple[
        dict[str, dict[str, float]],
        dict[str, dict[str, float]],
        dict[str, dict],
        list[str],
    ]:
        """加载行情、ATR 与市场状态。

        Returns:
            price_map:      {code: {date_str: close}}
            atr_map:        {code: {date_str: atr_pct}}
            market_regime:  {date_str: {state, score, data}}
            trading_days:   区间内交易日（升序）
        """
        fetch_start = start - timedelta(days=1500)
        price_map: dict[str, dict[str, float]] = {}
        atr_map: dict[str, dict[str, float]] = {}

        for code in codes:
            quotes = quote_repo.find_by_code_in_range(code, fetch_start, end)
            price_map[code] = {str(q.date): float(q.close) for q in quotes}

            atr: dict[str, float] = {}
            for ind in indicators_repo.find_by_code_between(code, start, end):
                value = ind.data.get("atr_pct")
                if value is not None:
                    atr[str(ind.date)] = float(value)
            atr_map[code] = atr

        regimes = market_regime_repo.find_between(start, end)
        market_regime_map = {
            str(r.date): {"state": r.state, "score": r.score, "data": r.data}
            for r in regimes
        }

        trading_days = self.calendar.get_trading_days_in_range(start, end)
        return price_map, atr_map, market_regime_map, trading_days

    # ── 主入口 ──

    def run(self, codes: list[str], start: date, end: date) -> dict[str, Any]:
        """运行回测，返回净值曲线、交易、业绩摘要与规则命中统计。"""
        price_map, atr_map, market_regime_map, trading_days = \
            self.load_data(codes, start, end)
        trading_day_set = set(trading_days)
        meta = {
            "start": str(start), "end": str(end), "codes": codes,
            "capital": self.initial_capital, "cost_ratio": self.cost_ratio,
            "slippage": self.slippage, "position_limit": self.position_limit,
        }

        signal_df = self._load_signals(codes, start, end)
        if signal_df.empty:
            return {"meta": meta, "versions": {}}

        regime_by_day = self._precompute_per_code_regimes(trading_days, market_regime_map)
        logger.info(f"回测 {VERSION}: {len(signal_df)} 条信号, {len(codes)} 只 ETF")

        equity_curve, trades, stats = self._run(
            signal_df, codes, price_map, atr_map,
            trading_days, trading_day_set, regime_by_day,
        )
        summary = self._compute_summary(equity_curve, trades)
        return {
            "meta": meta,
            "versions": {
                VERSION: {
                    "equity_curve": equity_curve,
                    "trades": trades,
                    "summary": summary,
                    "stats": stats,
                }
            },
        }

    def _load_signals(self, codes: list[str], start: date, end: date) -> pd.DataFrame:
        """从 signals 表加载信号。"""
        rows = []
        for code in codes:
            for s in signals_repo.find_by_code_between(code, start, end):
                rows.append({
                    "code": code, "date": str(s.date),
                    "signal": s.signal, "signal_meta": s.signal_meta or {},
                })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values(["code", "date"]).reset_index(drop=True)

    def _precompute_per_code_regimes(
        self,
        trading_days: list[str],
        market_regime_map: dict[str, dict],
    ) -> dict[str, dict[str, dict]]:
        """按交易日预计算每只 ETF 所属市场的状态。"""
        code_regime_groups = {
            code: self.code_regime_groups.get(code, "A股")
            for code in self.code_regime_groups
        }
        result: dict[str, dict[str, dict]] = {}
        for day_str in trading_days:
            base = market_regime_map.get(day_str, {"state": MarketState.UNKNOWN.value})
            result[day_str] = build_per_code_market_regime(
                code_regime_groups,
                date.fromisoformat(day_str),
                base,
                params=self.market_regime_params,
            )
        return result

    # ── 逐日推进 ──

    def _run(
        self,
        signal_df: pd.DataFrame,
        codes: list[str],
        price_map: dict[str, dict[str, float]],
        atr_map: dict[str, dict[str, float]],
        trading_days: list[str],
        trading_day_set: set[str],
        regime_by_day: dict[str, dict[str, dict]],
    ) -> tuple[list[EquityPoint], list[TradeLog], dict]:
        portfolio = PortfolioState(cash=self.initial_capital)
        equity_curve: list[EquityPoint] = []
        trades: list[TradeLog] = []
        stats = _new_stats()

        pending: dict[str, list[dict]] = {}
        last_stop_loss_exits: dict[str, dict[str, Any]] = {}
        day_index = {day: idx for idx, day in enumerate(trading_days)}

        sig_by_date: dict[str, list[dict]] = {}
        for _, row in signal_df.iterrows():
            sig_by_date.setdefault(row["date"], []).append(row.to_dict())

        for day_str in trading_days:
            day_date = date.fromisoformat(day_str)
            day_sigs = sig_by_date.get(day_str, [])

            current_prices = {
                code: price
                for code in codes
                if (price := price_map.get(code, {}).get(day_str)) is not None
            }

            # 执行前一交易日生成、计划今日成交的建议
            for adv in pending.pop(day_str, []):
                code = adv["code"]
                exec_price = current_prices.get(code)
                if exec_price is None:
                    continue
                executed = self._execute_advice(
                    portfolio, code, adv["advice"], exec_price,
                    day_date, trades, current_prices,
                    signal_meta=adv.get("signal_meta", {}),
                    signal_source=adv.get("signal_source"),
                    reason=adv.get("blocked_reason"),
                    exec_index=day_index.get(day_str),
                    stats=stats,
                )
                if executed and executed.action == "SELL" and adv.get("signal_source") == "stop_loss":
                    last_stop_loss_exits[code] = {
                        "date": day_date,
                        "price": exec_price,
                        "trading_index": day_index.get(day_str),
                    }

            mv = portfolio.market_value_at(current_prices)
            equity_curve.append(EquityPoint(
                date=day_date, cash=portfolio.cash,
                market_value=mv, total_equity=portfolio.cash + mv,
                version=VERSION,
            ))

            exec_day = self.calendar.get_next_trading_day(day_str)
            if exec_day is None or exec_day not in trading_day_set:
                continue

            # 1) 风控
            risk_signals = self._check_risk(
                portfolio, price_map, atr_map, day_str, day_date
            )
            for rs in risk_signals.values():
                if rs.get("source") == "stop_loss":
                    stats["stop_loss_triggered"] += 1
                elif rs.get("source") == "max_holding":
                    stats["max_holding_exit"] += 1

            # 2) 持仓快照
            pos_list = [{
                "id": hash(code),
                "code": code,
                "cost": pos.avg_cost,
                "shares": pos.shares,
                "entry_date": pos.entry_date or day_date,
            } for code, pos in portfolio.positions.items()]

            # 3) 分市场状态
            regime = regime_by_day.get(day_str)

            if day_sigs or risk_signals:
                signal_codes = {row["code"] for row in day_sigs}
                for code in set(risk_signals) - signal_codes:
                    day_sigs = list(day_sigs) + [{
                        "code": code,
                        "date": day_str,
                        "signal": SignalType.HOLD.value,
                        "signal_meta": {},
                    }]
                advices = generate_advice(
                    positions=pos_list,
                    signals=pd.DataFrame(day_sigs),
                    current_prices=current_prices,
                    risk_signals=risk_signals,
                    market_regime=regime,
                    last_buy_dates=self._get_last_buy_dates(trades, codes),
                    add_cooldown_days=self.cooldown_days,
                )
            else:
                advices = []

            # 4) 拦截统计
            for adv in advices:
                if (adv["advice"] in (AdviceAction.WATCH.value, AdviceAction.HOLD.value)
                        and adv.get("signal_source") == "market_regime"):
                    stats["market_blocked"] += 1
                if (adv["advice"] == AdviceAction.HOLD.value
                        and adv.get("signal_source") == "add_cooldown"):
                    stats["cooldown_blocked"] += 1

            # 5) 计划次日成交
            signal_meta_by_code = {
                row["code"]: row.get("signal_meta", {}) or {} for row in day_sigs
            }
            executable = []
            for adv in advices:
                if adv["advice"] not in (AdviceAction.OPEN.value,
                                         AdviceAction.ADD.value,
                                         AdviceAction.SELL.value):
                    continue
                enriched = dict(adv)
                enriched["signal_meta"] = signal_meta_by_code.get(adv["code"], {})
                if adv["advice"] == AdviceAction.OPEN.value:
                    self._mark_reentry(enriched, last_stop_loss_exits, stats)
                executable.append(enriched)
            if executable:
                pending.setdefault(exec_day, []).extend(executable)

        return equity_curve, trades, stats

    @staticmethod
    def _mark_reentry(
        advice: dict,
        last_stop_loss_exits: dict[str, dict[str, Any]],
        stats: dict,
    ) -> None:
        """标记止损后再入场（只做统计，不设过滤规则）。"""
        if advice["code"] not in last_stop_loss_exits:
            return
        stats["reentry_attempts"] += 1
        stats["reentry_allowed"] += 1
        advice["is_reentry_entry"] = True
        last_stop_loss_exits.pop(advice["code"], None)

    # ── 执行 ──

    def _execute_advice(
        self,
        portfolio: PortfolioState,
        code: str,
        action: str,
        exec_price: float,
        exec_date: date,
        trades: list[TradeLog],
        market_prices: dict[str, float],
        signal_meta: dict | None = None,
        signal_source: str | None = None,
        reason: str | None = None,
        exec_index: int | None = None,
        stats: dict | None = None,
    ) -> TradeLog | None:
        """在资金与仓位约束下执行一条建议。"""
        signal_meta = signal_meta or {}
        stats = stats if stats is not None else _new_stats()
        for key, value in _new_stats().items():
            stats.setdefault(key, value)
        pos = portfolio.positions.get(code)
        price_with_cost = exec_price * (1 + self.slippage)

        if action in (AdviceAction.OPEN.value, AdviceAction.ADD.value):
            if action == AdviceAction.ADD.value:
                stats["add_attempts"] += 1
                if pos is None:
                    stats["add_rule_blocked"] += 1
                    return None
                if not self._add_budget_allows(pos, exec_price, signal_meta, stats):
                    return None

            max_pos_value = portfolio.total_equity_at(market_prices) * self.position_limit
            current_pos_value = pos.shares * exec_price if pos else 0.0
            remaining = max_pos_value - current_pos_value
            affordable = portfolio.cash - remaining * self.cost_ratio

            if affordable <= 0 or remaining <= 0:
                return None

            buy_value = self._planned_buy_value(
                action=action,
                pos=pos,
                max_pos_value=max_pos_value,
                remaining=remaining,
                affordable=affordable,
                cash=portfolio.cash,
                code=code,
                signal_meta=signal_meta,
                stats=stats,
            )
            if buy_value <= 0 or buy_value < price_with_cost * 100:
                return None

            shares = int(buy_value / price_with_cost / 100) * 100
            if shares <= 0:
                return None

            cost_total = shares * price_with_cost
            commission = cost_total * self.cost_ratio
            total_cost = cost_total + commission
            if total_cost > portfolio.cash:
                return None

            cash_before = portfolio.cash
            portfolio.cash -= total_cost

            if pos:
                pos.shares += shares
                pos.cost += cost_total
                pos.used_budget += cost_total
                if action == AdviceAction.ADD.value:
                    pos.add_count += 1
                    pos.last_add_date = exec_date
            else:
                portfolio.positions[code] = Position(
                    code=code, shares=shares, cost=cost_total,
                    entry_date=exec_date, last_add_date=exec_date,
                    target_budget=self._position_target_budget(
                        max_pos_value, code, signal_meta,
                    ),
                    used_budget=cost_total,
                )

            trade = TradeLog(
                code=code, date=exec_date, action=action,
                price=exec_price, shares=shares, cost=commission,
                cash_before=cash_before, cash_after=portfolio.cash,
                version=VERSION, signal_source=signal_source, reason=reason,
            )
            trades.append(trade)
            if action == AdviceAction.ADD.value:
                stats["add_executed"] += 1
                stats["add_shares_total"] += shares
            return trade

        if action == AdviceAction.SELL.value and pos and pos.shares > 0:
            cash_before = portfolio.cash
            sale_value = pos.shares * exec_price * (1 - self.slippage)
            commission = sale_value * self.cost_ratio
            portfolio.cash += sale_value - commission
            trade = TradeLog(
                code=code, date=exec_date, action="SELL",
                price=exec_price, shares=pos.shares, cost=commission,
                cash_before=cash_before, cash_after=portfolio.cash,
                version=VERSION, signal_source=signal_source, reason=reason,
            )
            trades.append(trade)
            del portfolio.positions[code]
            return trade
        return None

    def _planned_buy_value(
        self,
        action: str,
        pos: Position | None,
        max_pos_value: float,
        remaining: float,
        affordable: float,
        cash: float,
        code: str,
        signal_meta: dict,
        stats: dict,
    ) -> float:
        """按 70/15/15 预算计算本次买入金额。"""
        entry_ratio = float(self.entry_add_budget.get("entry_ratio", 1.0))
        steps = self.entry_add_budget.get("add_steps", [])

        if action == AdviceAction.OPEN.value:
            target_budget = self._position_target_budget(max_pos_value, code, signal_meta)
            if target_budget < max_pos_value:
                stats["quality_budget_scaled"] += 1
            return min(target_budget * entry_ratio, remaining, affordable, cash * 0.95)

        if action == AdviceAction.ADD.value and pos is not None:
            if pos.add_count >= len(steps):
                return 0.0
            reserve_ratio = float(steps[pos.add_count].get("ratio", 0.0))
            target_budget = pos.target_budget or max_pos_value
            planned = target_budget * reserve_ratio
            reserve_left = max(target_budget - pos.used_budget, 0.0)
            return min(planned, reserve_left, remaining, affordable, cash * 0.95)

        return 0.0

    def _position_target_budget(
        self, max_pos_value: float, code: str, signal_meta: dict,
    ) -> float:
        """建仓时锁定的目标预算（含 high_vol 质量分层缩放）。"""
        return max_pos_value * self._quality_multiplier(code, signal_meta)

    def _quality_multiplier(self, code: str, signal_meta: dict) -> float:
        """high_vol 按 score 分层缩放预算；其他 ETF 不缩放。"""
        if self.code_volatility_groups.get(code, "unknown_vol") != "high_vol":
            return 1.0
        score = _as_float(signal_meta.get("score"))
        if score is not None and score >= QUALITY_STRONG_SCORE:
            return QUALITY_STRONG_MULTIPLIER
        if score is not None and score >= QUALITY_MEDIUM_SCORE:
            return QUALITY_MEDIUM_MULTIPLIER
        return QUALITY_WEAK_MULTIPLIER

    def _add_budget_allows(
        self, pos: Position, exec_price: float, signal_meta: dict, stats: dict,
    ) -> bool:
        """加仓阶梯校验：步数、浮盈、分数、预算余额。"""
        steps = self.entry_add_budget.get("add_steps", [])
        if not steps or pos.add_count >= len(steps):
            stats["add_rule_blocked"] += 1
            return False

        step = steps[pos.add_count]
        if step.get("require_profit", True) and exec_price <= pos.avg_cost:
            stats["add_rule_blocked"] += 1
            return False

        min_score = step.get("min_score")
        if min_score is not None:
            score = _as_float(signal_meta.get("score"))
            if score is None or score < float(min_score):
                stats["add_rule_blocked"] += 1
                return False

        if pos.target_budget > 0 and pos.used_budget >= pos.target_budget:
            stats["add_rule_blocked"] += 1
            return False
        return True

    # ── 风控 ──

    def _check_risk(
        self,
        portfolio: PortfolioState,
        price_map: dict[str, dict[str, float]],
        atr_map: dict[str, dict[str, float]],
        day_str: str,
        day_date: date,
    ) -> dict[str, dict]:
        """逐仓检查风控规则链，返回 {code: risk_signal}。"""
        risk_signals: dict[str, dict] = {}
        for code, pos in portfolio.positions.items():
            close = price_map.get(code, {}).get(day_str)
            if close is None or pos.entry_date is None:
                continue
            result = self.risk.check_position(
                {
                    "id": hash(code),
                    "code": code,
                    "cost": pos.avg_cost,
                    "shares": pos.shares,
                    "entry_date": pos.entry_date,
                    "as_of_date": day_date,
                    "stop_loss_profile": self.code_stop_loss_profiles.get(code),
                    "atr_pct": atr_map.get(code, {}).get(day_str),
                },
                close,
            )
            if result is None:
                continue
            risk_signals[code] = {
                "signal": "SELL",
                "source": result.source,
                "reason": result.reason,
                "stop_loss_profile": self.code_stop_loss_profiles.get(code),
            }
        return risk_signals

    # ── 辅助 ──

    @staticmethod
    def _get_last_buy_dates(trades: list[TradeLog], codes: list[str]) -> dict[str, date]:
        """各 ETF 最近一次买入日期，供加仓冷却使用。"""
        last: dict[str, date] = {}
        for t in reversed(trades):
            if t.action in ("BUY", "建仓", "加仓") and t.code not in last:
                last[t.code] = t.date
        for code in codes:
            last.setdefault(code, date.min)
        return last

    def _compute_summary(self, equity_curve: list[EquityPoint],
                         trades: list[TradeLog]) -> dict[str, Any]:
        if not equity_curve:
            return {"error": "no_equity_data"}
        from src.backtest.portfolio_metrics import calculate_metrics
        return calculate_metrics(equity_curve, trades, self.initial_capital)


def _new_stats() -> dict[str, int | float]:
    return {
        "market_blocked": 0,
        "cooldown_blocked": 0,
        "stop_loss_triggered": 0,
        "max_holding_exit": 0,
        "add_attempts": 0,
        "add_executed": 0,
        "add_rule_blocked": 0,
        "add_shares_total": 0.0,
        "quality_budget_scaled": 0,
        "reentry_attempts": 0,
        "reentry_allowed": 0,
    }


def run_portfolio_backtest(
    codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    capital: float = 100_000.0,
    cost_ratio: float = 0.0005,
    slippage: float = 0.0001,
    position_limit: float = 0.3,
) -> dict[str, Any]:
    """便捷入口：加载 settings.yaml 并运行回测。"""
    from src.config import load_config
    config = load_config()

    if codes is None:
        codes = [e.symbol for e in config.etf_list]
    code_regime_groups = {e.symbol: e.regime_group for e in config.etf_list}
    code_stop_loss_profiles = {e.symbol: e.stop_loss_profile for e in config.etf_list}
    code_volatility_groups = {e.symbol: e.volatility_group for e in config.etf_list}

    calendar = TradingCalendarService()
    if end is None:
        end = date.fromisoformat(calendar.get_previous_trading_day())
    if start is None:
        start = end - timedelta(days=config.lookback_days)

    bt = PortfolioBacktest(
        calendar=calendar,
        initial_capital=capital,
        cost_ratio=cost_ratio,
        slippage=slippage,
        position_limit=position_limit,
        cooldown_days=config.strategy_params.get("cooldown_days", 5),
        market_regime_params=config.market_regime_params,
        code_regime_groups=code_regime_groups,
        code_stop_loss_profiles=code_stop_loss_profiles,
        code_volatility_groups=code_volatility_groups,
        entry_add_budget=config.strategy_params.get("entry_add_budget", {}),
        risk_controller=RiskController(config),
    )
    return bt.run(codes, start, end)


def format_portfolio_report(result: dict[str, Any]) -> str:
    """格式化回测报告。"""
    lines = ["=" * 72, "  组合净值回测报告", "=" * 72]
    meta = result["meta"]
    lines.append(f"  初始资金: {meta['capital']:,.0f} 元")
    lines.append(f"  交易成本: 佣金 {meta['cost_ratio']:.4f} + 滑点 {meta['slippage']:.4f}")
    lines.append(f"  仓位上限: {meta['position_limit']:.0%}")
    lines.append(f"  回测区间: {meta['start']} ~ {meta['end']}")
    lines.append(f"  ETF 数量: {len(meta['codes'])}")
    lines.append("")

    headers = ["版本", "年化收益", "最大回撤", "Calmar", "Sharpe",
               "胜率", "利润因子", "交易次数", "换手率"]
    cols = [14, 10, 10, 8, 8, 8, 10, 10, 8]
    lines.append("  " + "  ".join(h.ljust(c) for h, c in zip(headers, cols)))
    lines.append("  " + "  ".join("-" * c for c in cols))

    for name, v in result["versions"].items():
        s = v["summary"]
        lines.append(
            f"  {name:14s}"
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


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed
