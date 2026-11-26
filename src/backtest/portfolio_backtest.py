"""真实账户净值口径回测引擎。

每日跟踪 cash + positions × close = total_equity，
支持多 ETF 同时持仓、资金约束、交易成本和版本对比。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.advisor import generate_advice
from src.backtest.ablation_config import (
    AblationExperimentConfig,
    HighVolFrequencyControlRuleConfig,
    PortfolioRiskRuleConfig,
    HighVolQualityControlRuleConfig,
    VolatilityStrategyRuleConfig,
    legacy_portfolio_experiments,
    stop_loss_rule_from_profile,
)
from src.backtest.experimental_signals import build_experimental_signal_frame
from src.backtest.relative_strength import (
    apply_relative_strength_rule,
    build_relative_strength_score_map,
    market_benchmark_for_regime_group,
    sort_by_relative_strength,
)
from src.database import (
    indicators_repo,
    market_index_quote_repo,
    market_regime_repo,
    quote_repo,
    signals_repo,
)
from src.models import MarketState, SignalType
from src.service.calendar_service import TradingCalendarService
from src.service.market_regime_service import build_per_code_market_regime
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
    peak_price: float = 0.0
    entry_trading_index: int | None = None
    last_add_trading_index: int | None = None
    target_budget: float = 0.0
    used_budget: float = 0.0
    add_count: int = 0
    is_reentry: bool = False

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
        market_regime_params: dict | None = None,
        code_regime_groups: dict[str, str] | None = None,
        code_stop_loss_profiles: dict[str, str] | None = None,
        code_volatility_groups: dict[str, str] | None = None,
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

    # ── 数据加载 ──

    def load_data(
        self, codes: list[str], start: date, end: date
    ) -> tuple[
        dict[str, dict[str, float]],            # {code: {date_str: close}}
        dict[str, dict[str, dict]],             # {code: {date_str: odds_info}}
        dict[str, dict],                        # {date_str: regime_info}
        list[str],                              # 全部交易日
    ]:
        """加载回测所需的行情、赔率、市场热度和交易日。

        信号不在此加载：回测已统一为"同一份信号走多个 advisor 配置"的
        消融范式，信号由 _load_unified_signals 单独加载，不再按策略版本分组。

        Returns:
            price_map:          {code: {date_str: close}}
            odds_map_full:      {code: {date_str: {odds_state, odds_score, premium_blocked, ...}}}
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
                atr_pct = ind.data.get("atr_pct")
                if odds_state is None and atr_pct is None:
                    continue
                code_odds[d_str] = {
                    "odds_state": odds_state,
                    "odds_score": ind.data.get("odds_score"),
                    "premium_blocked": ind.data.get("odds_premium_blocked", False),
                    "atr_pct": atr_pct,
                    "ma20": ind.data.get("ma20"),
                    "ma60": ind.data.get("ma60"),
                    "rsi": ind.data.get("rsi"),
                    "dif": ind.data.get("dif"),
                    "dea": ind.data.get("dea"),
                    "adx14": ind.data.get("adx14"),
                }
            odds_map_full[code] = code_odds

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
        return self.run_experiments(codes, start, end, legacy_portfolio_experiments())

    def run_experiments(
        self,
        codes: list[str],
        start: date,
        end: date,
        experiments: list[AblationExperimentConfig],
    ) -> dict[str, Any]:
        """运行一组回测实验配置。"""
        price_map, odds_map_full, market_regime_map, trading_days = \
            self.load_data(codes, start, end)
        trading_day_set = set(trading_days)
        per_code_regime_by_day = self._precompute_per_code_regimes(
            codes=codes,
            trading_days=trading_days,
            market_regime_map=market_regime_map,
            experiments=experiments,
        )

        signal_df = self._load_unified_signals(codes, start, end)
        if signal_df.empty:
            return {"meta": {"start": str(start), "end": str(end), "codes": codes,
                            "capital": self.initial_capital, "cost_ratio": self.cost_ratio,
                            "slippage": self.slippage, "position_limit": self.position_limit},
                    "versions": {}}

        result = {}
        benchmark_price_map = self._load_benchmark_price_map(codes, start, end, experiments)
        code_benchmark_indices = {
            code: market_benchmark_for_regime_group(self.code_regime_groups.get(code, "A股"))
            for code in codes
        }
        experimental_signal_cache: dict[str, pd.DataFrame] = {}
        for exp in experiments:
            exp_signal_df = signal_df
            if exp.experimental_signal_profile is not None:
                profile_name = exp.experimental_signal_profile.name
                if profile_name not in experimental_signal_cache:
                    experimental_signal_cache[profile_name] = build_experimental_signal_frame(
                        codes=codes,
                        start=start,
                        end=end,
                        profile=exp.experimental_signal_profile,
                        price_map=price_map,
                        code_volatility_groups=self.code_volatility_groups,
                        fallback_signal_df=signal_df,
                    )
                exp_signal_df = experimental_signal_cache[profile_name]
            logger.info(f"回测 {exp.name}: {len(exp_signal_df)} 条信号, {len(codes)} 只 ETF")
            rs_score_map = None
            if exp.relative_strength_rule is not None:
                rs_score_map = build_relative_strength_score_map(
                    signal_rows=exp_signal_df.to_dict("records"),
                    price_map=price_map,
                    rule=exp.relative_strength_rule,
                    benchmark_price_map=benchmark_price_map,
                    code_benchmark_indices=code_benchmark_indices,
                )
            equity_curve, trades, stats = self._run_advisor_config(
                exp.name, exp_signal_df, codes, price_map,
                odds_map_full,
                market_regime_map,
                trading_days,
                trading_day_set,
                experiment=exp,
                benchmark_price_map=benchmark_price_map,
                code_benchmark_indices=code_benchmark_indices,
                rs_score_map=rs_score_map,
                per_code_regime_by_day=per_code_regime_by_day,
            )
            summary = self._compute_summary(equity_curve, trades, exp.name)
            result[exp.name] = {
                "equity_curve": equity_curve,
                "trades": trades,
                "summary": summary,
                "stats": stats,
                "experiment": exp.to_dict(),
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

    def _precompute_per_code_regimes(
        self,
        codes: list[str],
        trading_days: list[str],
        market_regime_map: dict[str, dict],
        experiments: list[AblationExperimentConfig],
    ) -> dict[str, dict[str, dict]]:
        """Precompute per-code market regime once for a whole experiment matrix."""
        if not any(exp.use_market_gate for exp in experiments):
            return {}

        code_regime_groups = {
            code: self.code_regime_groups.get(code, "A股")
            for code in codes
        }
        result: dict[str, dict[str, dict]] = {}
        for day_str in trading_days:
            base_regime = market_regime_map.get(day_str, {"state": "UNKNOWN"})
            result[day_str] = build_per_code_market_regime(
                code_regime_groups,
                date.fromisoformat(day_str),
                base_regime,
                params=self.market_regime_params,
            )
        return result

    def _load_benchmark_price_map(
        self,
        codes: list[str],
        start: date,
        end: date,
        experiments: list[AblationExperimentConfig],
    ) -> dict[str, dict[str, float]]:
        """Load market benchmarks required by RS excess-return experiments."""
        needs_benchmark = any(
            exp.relative_strength_rule is not None
            and exp.relative_strength_rule.score_kind == "excess"
            for exp in experiments
        )
        if not needs_benchmark:
            return {}

        indices = {
            market_benchmark_for_regime_group(self.code_regime_groups.get(code, "A股"))
            for code in codes
        }
        fetch_start = start - timedelta(days=180)
        result: dict[str, dict[str, float]] = {}
        for index_code in indices:
            quotes = market_index_quote_repo.find_by_code_in_range(
                index_code,
                fetch_start,
                end,
            )
            result[index_code] = {
                str(quote.date): float(quote.close)
                for quote in quotes
                if quote.close is not None and quote.close > 0
            }
        return result

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
        experiment: AblationExperimentConfig | None = None,
        benchmark_price_map: dict[str, dict[str, float]] | None = None,
        code_benchmark_indices: dict[str, str] | None = None,
        rs_score_map: dict[tuple[str, str], float | None] | None = None,
        per_code_regime_by_day: dict[str, dict[str, dict]] | None = None,
    ) -> tuple[list[EquityPoint], list[TradeLog], dict]:
        """单配置回测：逐日推进，资金约束下执行。"""
        experiment = experiment or AblationExperimentConfig(name=version, label=version)
        portfolio = PortfolioState(cash=self.initial_capital)
        equity_curve: list[EquityPoint] = []
        trades: list[TradeLog] = []
        stats = {
            "premium_blocked": 0,
            "market_blocked": 0,
            "cooldown_blocked": 0,
            "stop_loss_triggered": 0,
            "max_holding_exit": 0,
            "add_attempts": 0,
            "add_executed": 0,
            "add_rule_blocked": 0,
            "add_rule_scaled": 0,
            "add_shares_total": 0.0,
            "reentry_attempts": 0,
            "reentry_allowed": 0,
            "reentry_blocked": 0,
            "reentry_executed": 0,
            "reentry_closed": 0,
            "reentry_wins": 0,
            "reentry_stop_loss_exit": 0,
            "reentry_pnl_total": 0.0,
            "reentry_pnl_pct_total": 0.0,
            "rs_buy_candidates": 0,
            "rs_buy_allowed": 0,
            "rs_buy_blocked": 0,
            "rs_scores_missing": 0,
            "vol_entry_candidates": 0,
            "vol_entry_allowed": 0,
            "vol_entry_blocked": 0,
            "vol_add_candidates": 0,
            "vol_add_allowed": 0,
            "vol_add_blocked": 0,
            "trailing_stop_exit": 0,
            "trend_exit": 0,
            "structure_exit": 0,
            "disaster_stop": 0,
            "freq_buy_blocked": 0,
            "freq_sell_blocked": 0,
            "freq_min_hold_blocked": 0,
            "freq_add_interval_blocked": 0,
            "freq_max_positions_blocked": 0,
            "quality_entry_candidates": 0,
            "quality_entry_allowed": 0,
            "quality_entry_blocked": 0,
            "quality_daily_limit_blocked": 0,
            "quality_add_candidates": 0,
            "quality_add_allowed": 0,
            "quality_add_blocked": 0,
            "quality_budget_scaled": 0,
            "portfolio_risk_blocked": 0,
            "portfolio_risk_scaled": 0,
            "portfolio_risk_position_count_blocked": 0,
            "portfolio_risk_high_vol_count_blocked": 0,
            "portfolio_risk_single_position_scaled": 0,
            "portfolio_risk_single_position_blocked": 0,
            "portfolio_risk_total_exposure_blocked": 0,
            "portfolio_risk_total_exposure_scaled": 0,
            "portfolio_risk_high_vol_exposure_blocked": 0,
            "portfolio_risk_high_vol_exposure_scaled": 0,
        }
        pending_advices: dict[str, list[dict]] = {}
        last_stop_loss_exits: dict[str, dict[str, Any]] = {}
        trading_day_index = {day: idx for idx, day in enumerate(trading_days)}
        buy_streak_by_code: dict[str, int] = {}
        sell_streak_by_code: dict[str, int] = {}

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

            if experiment.relative_strength_rule is not None and day_sigs:
                day_sigs, rs_stats = apply_relative_strength_rule(
                    day_str=day_str,
                    signal_rows=day_sigs,
                    price_map=price_map,
                    rule=experiment.relative_strength_rule,
                    benchmark_price_map=benchmark_price_map,
                    code_benchmark_indices=code_benchmark_indices,
                    score_map=rs_score_map,
                )
                for key, value in rs_stats.items():
                    stats[key] = stats.get(key, 0) + value

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
                executed = self._execute_advice(
                    portfolio, code, adv["advice"], exec_price,
                    day_date, version, trades, current_prices,
                    experiment=experiment,
                    signal_meta=adv.get("signal_meta", {}),
                    signal_source=adv.get("signal_source"),
                    reason=adv.get("blocked_reason"),
                    is_reentry_entry=adv.get("is_reentry_entry", False),
                    exec_trading_index=trading_day_index.get(day_str),
                    stats=stats,
                )
                if executed and executed.action == "SELL" and adv.get("signal_source") == "stop_loss":
                    last_stop_loss_exits[code] = {
                        "date": day_date,
                        "price": exec_price,
                        "trading_index": trading_day_index.get(day_str),
                    }
                elif executed and executed.action in ("BUY", "建仓") and adv.get("is_reentry_entry"):
                    last_stop_loss_exits.pop(code, None)

            for code, pos in portfolio.positions.items():
                close = current_prices.get(code)
                if close is not None:
                    pos.peak_price = max(pos.peak_price or close, close)

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
            day_risk_data = {
                code: odds_map.get(code, {}).get(day_str, {})
                for code in codes
            } if odds_map is not None else {}
            risk_signals = self._check_risk(
                portfolio,
                price_map,
                day_str,
                use_stop_loss=experiment.use_stop_loss,
                max_holding_days=experiment.max_holding_days,
                experiment=experiment,
                risk_data=day_risk_data,
            )
            for rs in risk_signals.values():
                if rs.get("source") == "stop_loss":
                    stats["stop_loss_triggered"] += 1
                elif rs.get("source") == "max_holding":
                    stats["max_holding_exit"] += 1
                elif rs.get("source") == "trailing_stop":
                    stats["trailing_stop_exit"] += 1
                elif rs.get("source") == "trend_exit":
                    stats["trend_exit"] += 1
                elif rs.get("source") == "structure_exit":
                    stats["structure_exit"] += 1
                elif rs.get("source") == "disaster_stop":
                    stats["disaster_stop"] += 1

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

            # 3) 构建分市场 regime
            base_regime = (
                market_regime_map.get(day_str, {"state": "UNKNOWN"})
                if experiment.use_market_gate and market_regime_map else None
            )
            if experiment.use_market_gate and per_code_regime_by_day:
                regime = per_code_regime_by_day.get(day_str)
            elif base_regime and codes:
                regime = build_per_code_market_regime(
                    {
                        code: self.code_regime_groups.get(code, "A股")
                        for code in codes
                    },
                    day_date,
                    base_regime,
                    params=self.market_regime_params,
                )
            else:
                regime = base_regime

            last_buy_dates = self._get_last_buy_dates(trades, codes)
            day_odds_map = None
            if odds_map is not None:
                day_odds_map = {
                    code: odds_map.get(code, {}).get(day_str, {})
                    for code in codes
                }
            if day_sigs:
                day_sigs = self._apply_high_vol_frequency_signal_filter(
                    signal_rows=day_sigs,
                    portfolio=portfolio,
                    day_index=trading_day_index.get(day_str),
                    experiment=experiment,
                    buy_streak_by_code=buy_streak_by_code,
                    sell_streak_by_code=sell_streak_by_code,
                    stats=stats,
                )

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
                    use_premium_gate=experiment.use_premium_gate,
                    use_market_gate=experiment.use_market_gate,
                    use_add_cooldown=experiment.use_add_cooldown,
                )
            else:
                advices = []

            # 5) 统计拦截
            signal_by_code = {row["code"]: row["signal"] for row in day_sigs}
            for adv in advices:
                if adv["advice"] in ("观望", "继续持有") and adv.get("signal_source") == "market_regime":
                    stats["market_blocked"] += 1
                if adv["advice"] == "继续持有" and adv.get("signal_source") == "add_cooldown":
                    stats["cooldown_blocked"] += 1
                if (
                    experiment.use_premium_gate
                    and signal_by_code.get(adv["code"]) == SignalType.BUY.value
                    and adv["advice"] in ("观望", "继续持有")
                    and adv.get("signal_source") == "trend"
                    and day_odds_map is not None
                    and day_odds_map.get(adv["code"], {}).get("premium_blocked", False)
                ):
                    stats["premium_blocked"] += 1

            # 6) 缓存操作建议，下一交易日按收盘价模拟成交。
            signal_meta_by_code = {
                row["code"]: row.get("signal_meta", {}) or {}
                for row in day_sigs
            }
            executable = []
            planned_high_vol_entries = 0
            for adv in advices:
                if adv["advice"] not in ("建仓", "加仓", "卖出"):
                    continue
                enriched = dict(adv)
                enriched["signal_meta"] = signal_meta_by_code.get(adv["code"], {})
                allowed, planned_high_vol_entries = self._high_vol_frequency_allows_advice(
                    advice=enriched,
                    portfolio=portfolio,
                    day_index=trading_day_index.get(day_str),
                    experiment=experiment,
                    planned_high_vol_entries=planned_high_vol_entries,
                    stats=stats,
                )
                if not allowed:
                    continue
                if not self._volatility_entry_allows_advice(enriched, experiment, stats):
                    continue
                if not self._high_vol_quality_allows_entry(enriched, experiment, stats):
                    continue
                if not self._reentry_allows_advice(
                    enriched,
                    current_prices=current_prices,
                    day_risk_data=day_risk_data,
                    signal_date=day_date,
                    experiment=experiment,
                    last_stop_loss_exits=last_stop_loss_exits,
                    signal_day_index=trading_day_index.get(day_str),
                    stats=stats,
                ):
                    continue
                executable.append(enriched)
            if executable:
                executable = self._apply_high_vol_quality_daily_limit(
                    executable,
                    experiment,
                    stats,
                )
                executable = self._order_executable_advices(executable, experiment)
                pending_advices.setdefault(exec_day_str, []).extend(executable)

        return equity_curve, trades, stats

    def _apply_high_vol_frequency_signal_filter(
        self,
        *,
        signal_rows: list[dict],
        portfolio: PortfolioState,
        day_index: int | None,
        experiment: AblationExperimentConfig,
        buy_streak_by_code: dict[str, int],
        sell_streak_by_code: dict[str, int],
        stats: dict,
    ) -> list[dict]:
        """Apply high-vol BUY/SELL confirmation before advisor decisions."""
        rule = experiment.high_vol_frequency_rule
        if rule is None:
            return signal_rows

        filtered = []
        for row in signal_rows:
            code = row["code"]
            signal = row.get("signal")
            if not self._high_vol_frequency_rule_applies_to_code(code, experiment):
                filtered.append(row)
                continue

            if signal == SignalType.BUY.value:
                buy_streak_by_code[code] = buy_streak_by_code.get(code, 0) + 1
            else:
                buy_streak_by_code[code] = 0
            if signal == SignalType.SELL.value:
                sell_streak_by_code[code] = sell_streak_by_code.get(code, 0) + 1
            else:
                sell_streak_by_code[code] = 0

            pos = portfolio.positions.get(code)
            blocked_reason = None
            if (
                signal == SignalType.BUY.value
                and pos is None
                and rule.buy_confirm_days > 1
                and buy_streak_by_code.get(code, 0) < rule.buy_confirm_days
            ):
                blocked_reason = f"buy_confirm:{rule.buy_confirm_days}"
                stats["freq_buy_blocked"] = stats.get("freq_buy_blocked", 0) + 1

            if signal == SignalType.SELL.value and pos is not None:
                holding_days = (
                    day_index - pos.entry_trading_index
                    if day_index is not None and pos.entry_trading_index is not None
                    else None
                )
                if (
                    blocked_reason is None
                    and rule.min_holding_trading_days > 0
                    and holding_days is not None
                    and holding_days < rule.min_holding_trading_days
                ):
                    blocked_reason = f"min_holding:{rule.min_holding_trading_days}"
                    stats["freq_min_hold_blocked"] = stats.get("freq_min_hold_blocked", 0) + 1
                if (
                    blocked_reason is None
                    and rule.sell_confirm_days > 1
                    and sell_streak_by_code.get(code, 0) < rule.sell_confirm_days
                ):
                    blocked_reason = f"sell_confirm:{rule.sell_confirm_days}"
                    stats["freq_sell_blocked"] = stats.get("freq_sell_blocked", 0) + 1

            if blocked_reason is not None:
                filtered.append(self._blocked_signal_row(row, blocked_reason))
            else:
                filtered.append(row)
        return filtered

    @staticmethod
    def _blocked_signal_row(row: dict, reason: str) -> dict:
        """Return a HOLD row preserving metadata for frequency-control diagnostics."""
        blocked = dict(row)
        meta = dict(blocked.get("signal_meta", {}) or {})
        meta["frequency_blocked_reason"] = reason
        meta["blocked_original_signal"] = blocked.get("signal")
        blocked["signal"] = SignalType.HOLD.value
        blocked["signal_meta"] = meta
        return blocked

    def _high_vol_frequency_allows_advice(
        self,
        *,
        advice: dict,
        portfolio: PortfolioState,
        day_index: int | None,
        experiment: AblationExperimentConfig,
        planned_high_vol_entries: int,
        stats: dict,
    ) -> tuple[bool, int]:
        """Apply execution-side high-vol frequency controls."""
        rule = experiment.high_vol_frequency_rule
        if rule is None:
            return True, planned_high_vol_entries
        code = advice["code"]
        if not self._high_vol_frequency_rule_applies_to_code(code, experiment):
            return True, planned_high_vol_entries

        action = advice.get("advice")
        pos = portfolio.positions.get(code)
        if action == "建仓" and rule.max_high_vol_positions is not None:
            current_count = sum(
                1 for item in portfolio.positions.values()
                if self._high_vol_frequency_rule_applies_to_code(item.code, experiment)
            )
            if current_count + planned_high_vol_entries >= rule.max_high_vol_positions:
                stats["freq_max_positions_blocked"] = (
                    stats.get("freq_max_positions_blocked", 0) + 1
                )
                return False, planned_high_vol_entries
            return True, planned_high_vol_entries + 1

        if (
            action == "加仓"
            and pos is not None
            and rule.add_interval_trading_days > 0
            and day_index is not None
        ):
            ref_index = (
                pos.last_add_trading_index
                if pos.last_add_trading_index is not None
                else pos.entry_trading_index
            )
            if ref_index is not None and day_index - ref_index < rule.add_interval_trading_days:
                stats["freq_add_interval_blocked"] = (
                    stats.get("freq_add_interval_blocked", 0) + 1
                )
                return False, planned_high_vol_entries

        return True, planned_high_vol_entries

    @staticmethod
    def _order_executable_advices(
        executable: list[dict],
        experiment: AblationExperimentConfig,
    ) -> list[dict]:
        """Execute sells first, then rank BUY/ADD by RS score when enabled."""
        if experiment.relative_strength_rule is None:
            return executable
        sells = [adv for adv in executable if adv.get("advice") == "卖出"]
        buys = [adv for adv in executable if adv.get("advice") in ("建仓", "加仓")]
        others = [
            adv for adv in executable
            if adv.get("advice") not in ("卖出", "建仓", "加仓")
        ]
        return sells + sort_by_relative_strength(buys) + others

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
        experiment: AblationExperimentConfig,
        signal_meta: dict | None = None,
        signal_source: str | None = None,
        reason: str | None = None,
        is_reentry_entry: bool = False,
        exec_trading_index: int | None = None,
        stats: dict | None = None,
    ) -> TradeLog | None:
        """在资金约束下执行一条操作建议。"""
        signal_meta = signal_meta or {}
        stats = stats if stats is not None else {}
        pos = portfolio.positions.get(code)
        price_with_cost = exec_price * (1 + self.slippage)

        if advice_action in ("建仓", "加仓"):
            if advice_action == "加仓":
                stats["add_attempts"] = stats.get("add_attempts", 0) + 1
                if pos is None:
                    stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
                    return None
                if not self._high_vol_quality_allows_add(
                    code,
                    signal_meta,
                    experiment,
                    stats,
                ):
                    stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
                    return None
                if not self._add_allows_trade(pos, exec_price, signal_meta, experiment, stats):
                    return None

            # 计算可用资金和仓位上限
            position_limit = self.position_limit if experiment.use_position_limit else 1.0
            max_pos_value = portfolio.total_equity_at(market_prices) * position_limit
            current_pos_value = pos.shares * exec_price if pos else 0.0
            remaining = max_pos_value - current_pos_value
            affordable = portfolio.cash - remaining * self.cost_ratio  # 预留佣金

            if affordable <= 0 or remaining <= 0:
                return None  # 超限或现金不足

            buy_value = self._planned_buy_value(
                advice_action=advice_action,
                pos=pos,
                experiment=experiment,
                max_pos_value=max_pos_value,
                remaining=remaining,
                affordable=affordable,
                cash=portfolio.cash,
                code=code,
                signal_meta=signal_meta,
                stats=stats,
            )
            buy_value = self._apply_portfolio_risk_buy_value(
                buy_value=buy_value,
                portfolio=portfolio,
                code=code,
                pos=pos,
                exec_price=exec_price,
                market_prices=market_prices,
                experiment=experiment,
                stats=stats,
            )
            if buy_value <= 0:
                return None
            if buy_value < price_with_cost * 100:  # 至少买 100 股
                return None

            shares = int(buy_value / price_with_cost / 100) * 100  # 整手
            if shares <= 0:
                return None
            if advice_action == "加仓" and pos is not None:
                shares = self._cap_add_shares(shares, pos, experiment, stats)
                if shares <= 0:
                    stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
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
                if advice_action == "加仓":
                    pos.add_count += 1
                    pos.last_add_trading_index = exec_trading_index
            else:
                portfolio.positions[code] = Position(
                    code=code, shares=shares,
                    cost=cost_total, entry_date=exec_date,
                    peak_price=exec_price,
                    entry_trading_index=exec_trading_index,
                    target_budget=self._position_target_budget(
                        max_pos_value,
                        experiment,
                        code=code,
                        signal_meta=signal_meta,
                    ),
                    used_budget=cost_total,
                    is_reentry=is_reentry_entry,
                )

            trade = TradeLog(
                code=code, date=exec_date,
                action=advice_action, price=exec_price,
                shares=shares, cost=commission,
                cash_before=cash_before,
                cash_after=portfolio.cash,
                version=version,
                signal_source=signal_source,
                reason=reason,
            )
            trades.append(trade)
            if advice_action == "加仓":
                stats["add_executed"] = stats.get("add_executed", 0) + 1
                stats["add_shares_total"] = stats.get("add_shares_total", 0.0) + shares
            elif is_reentry_entry:
                stats["reentry_executed"] = stats.get("reentry_executed", 0) + 1
            return trade

        elif advice_action == "卖出" and pos and pos.shares > 0:
            cash_before = portfolio.cash
            sale_value = pos.shares * exec_price * (1 - self.slippage)
            commission = sale_value * self.cost_ratio
            portfolio.cash += sale_value - commission
            trade = TradeLog(
                code=code, date=exec_date,
                action="SELL", price=exec_price,
                shares=pos.shares, cost=commission,
                cash_before=cash_before,
                cash_after=portfolio.cash,
                version=version,
                signal_source=signal_source,
                reason=reason,
            )
            trades.append(trade)
            if pos.is_reentry:
                pnl_cash = (sale_value - commission) - pos.cost
                stats["reentry_closed"] = stats.get("reentry_closed", 0) + 1
                stats["reentry_pnl_total"] = stats.get("reentry_pnl_total", 0.0) + pnl_cash
                stats["reentry_pnl_pct_total"] = (
                    stats.get("reentry_pnl_pct_total", 0.0) + pnl_cash / pos.cost
                )
                if pnl_cash > 0:
                    stats["reentry_wins"] = stats.get("reentry_wins", 0) + 1
                if signal_source == "stop_loss":
                    stats["reentry_stop_loss_exit"] = stats.get("reentry_stop_loss_exit", 0) + 1
            del portfolio.positions[code]
            return trade
        return None

    def _reentry_allows_advice(
        self,
        advice: dict,
        current_prices: dict[str, float],
        day_risk_data: dict[str, dict],
        signal_date: date,
        experiment: AblationExperimentConfig,
        last_stop_loss_exits: dict[str, dict[str, Any]],
        signal_day_index: int | None,
        stats: dict,
    ) -> bool:
        """Apply reentry filters to new entries after a stop-loss exit."""
        if advice.get("advice") != "建仓":
            return True
        code = advice["code"]
        exit_info = last_stop_loss_exits.get(code)
        if exit_info is None:
            return True

        rule = experiment.reentry_rule
        if rule is not None and not self._reentry_rule_applies_to_code(rule, code):
            return True

        stats["reentry_attempts"] = stats.get("reentry_attempts", 0) + 1
        if rule is None:
            stats["reentry_allowed"] = stats.get("reentry_allowed", 0) + 1
            advice["is_reentry_entry"] = True
            return True

        # Idea 4: 止损后跳过第一个BUY信号，等第二个新BUY才重新入场
        if rule.skip_one_buy_after_stop and not exit_info.get("bounce_buy_skipped", False):
            exit_info["bounce_buy_skipped"] = True
            stats["reentry_blocked"] = stats.get("reentry_blocked", 0) + 1
            return False

        passed = self._reentry_rule_passed(
            rule=rule,
            advice=advice,
            current_price=current_prices.get(code),
            indicator_info=day_risk_data.get(code, {}),
            signal_date=signal_date,
            signal_day_index=signal_day_index,
            exit_info=exit_info,
        )
        if passed:
            stats["reentry_allowed"] = stats.get("reentry_allowed", 0) + 1
            advice["is_reentry_entry"] = True
            return True

        stats["reentry_blocked"] = stats.get("reentry_blocked", 0) + 1
        return False

    def _reentry_rule_applies_to_code(self, rule, code: str) -> bool:
        """Return whether a scoped reentry rule should affect this ETF."""
        if rule.volatility_groups:
            volatility_group = self.code_volatility_groups.get(code, "unknown_vol")
            if volatility_group not in rule.volatility_groups:
                return False
        if rule.regime_groups:
            regime_group = self.code_regime_groups.get(code, "A股")
            if regime_group not in rule.regime_groups:
                return False
        return True

    @staticmethod
    def _reentry_rule_passed(
        rule,
        advice: dict,
        current_price: float | None,
        indicator_info: dict,
        signal_date: date,
        exit_info: dict[str, Any],
        signal_day_index: int | None = None,
    ) -> bool:
        """Return whether a stop-loss reentry candidate passes the configured filter."""
        if current_price is None:
            return False

        exit_date = exit_info.get("date")
        exit_day_index = exit_info.get("trading_index")
        if rule.cooldown_trading_days > 0:
            if signal_day_index is None or exit_day_index is None:
                return False
            if signal_day_index - exit_day_index < rule.cooldown_trading_days:
                return False
        if rule.cooldown_days > 0 and exit_date is not None:
            if (signal_date - exit_date).days < rule.cooldown_days:
                return False

        signal_meta = advice.get("signal_meta", {}) or {}
        score = signal_meta.get("score")
        if rule.min_score is not None and (score is None or float(score) < rule.min_score):
            return False

        ma20 = _as_float(indicator_info.get("ma20"))
        ma60 = _as_float(indicator_info.get("ma60"))
        if rule.require_close_above_ma20 and (ma20 is None or current_price <= ma20):
            return False
        if rule.require_ma20_above_ma60 and (
            ma20 is None or ma60 is None or ma20 <= ma60
        ):
            return False

        if rule.require_price_above_stop_price:
            stop_price = _as_float(exit_info.get("price"))
            if stop_price is None or current_price <= stop_price:
                return False

        if rule.stop_price_atr_buffer is not None:
            atr_pct = _as_float(indicator_info.get("atr_pct"))
            stop_price = _as_float(exit_info.get("price"))
            if atr_pct is None or stop_price is None:
                return False
            atr_value = current_price * atr_pct
            if current_price < stop_price + rule.stop_price_atr_buffer * atr_value:
                return False

        adx = signal_meta.get("adx")
        if adx is None:
            adx = indicator_info.get("adx14")
        if rule.min_adx is not None and (adx is None or float(adx) < rule.min_adx):
            return False

        if rule.require_macd_positive:
            s_macd = signal_meta.get("s_macd")
            if s_macd is not None:
                if float(s_macd) <= 0:
                    return False
            else:
                dif = _as_float(indicator_info.get("dif"))
                dea = _as_float(indicator_info.get("dea"))
                if dif is None or dea is None or dif <= dea:
                    return False

        return True

    def _planned_buy_value(
        self,
        advice_action: str,
        pos: Position | None,
        experiment: AblationExperimentConfig,
        max_pos_value: float,
        remaining: float,
        affordable: float,
        cash: float,
        code: str,
        signal_meta: dict,
        stats: dict,
    ) -> float:
        """Calculate the target cash value for an entry or add execution."""
        rule = experiment.entry_add_budget_rule
        if rule is None:
            target_budget = self._position_target_budget(
                max_pos_value,
                experiment,
                code=code,
                signal_meta=signal_meta,
            )
            return min(target_budget, remaining, affordable, cash * 0.95)

        if advice_action == "建仓":
            target_budget = self._position_target_budget(
                max_pos_value,
                experiment,
                code=code,
                signal_meta=signal_meta,
            )
            if target_budget < max_pos_value:
                stats["quality_budget_scaled"] = stats.get("quality_budget_scaled", 0) + 1
            return min(target_budget * rule.entry_ratio, remaining, affordable, cash * 0.95)

        if advice_action == "加仓" and pos is not None:
            if pos.add_count >= len(rule.add_steps):
                return 0.0
            step = rule.add_steps[pos.add_count]
            target_budget = pos.target_budget or max_pos_value
            planned_step_value = target_budget * step.reserve_ratio
            reserve_left = max(target_budget - pos.used_budget, 0.0)
            return min(planned_step_value, reserve_left, remaining, affordable, cash * 0.95)

        return 0.0


    def _apply_portfolio_risk_buy_value(
        self,
        *,
        buy_value: float,
        portfolio: PortfolioState,
        code: str,
        pos: Position | None,
        exec_price: float,
        market_prices: dict[str, float],
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> float:
        """Apply portfolio-level exposure and concentration caps to a planned buy."""
        rule = experiment.portfolio_risk_rule
        if rule is None or buy_value <= 0:
            return buy_value

        total_equity = portfolio.total_equity_at(market_prices)
        if total_equity <= 0:
            return 0.0

        current_pos_value = pos.shares * exec_price if pos is not None else 0.0
        is_new_position = pos is None or pos.shares <= 0
        is_high_vol = self.code_volatility_groups.get(code, "unknown_vol") == "high_vol"

        if is_new_position and rule.max_positions is not None:
            if len(portfolio.positions) >= rule.max_positions:
                self._record_portfolio_risk_block(stats, "portfolio_risk_position_count_blocked")
                return 0.0

        if is_new_position and is_high_vol and rule.max_high_vol_positions is not None:
            high_count = sum(
                1 for item in portfolio.positions.values()
                if self.code_volatility_groups.get(item.code, "unknown_vol") == "high_vol"
            )
            if high_count >= rule.max_high_vol_positions:
                self._record_portfolio_risk_block(stats, "portfolio_risk_high_vol_count_blocked")
                return 0.0

        capped_value = buy_value
        if rule.max_single_position_ratio is not None:
            allowed = rule.max_single_position_ratio * total_equity - current_pos_value
            capped_value = self._cap_portfolio_risk_value(
                capped_value,
                allowed,
                stats,
                scaled_key="portfolio_risk_single_position_scaled",
                blocked_key="portfolio_risk_single_position_blocked",
            )
            if capped_value <= 0:
                return 0.0

        if rule.max_total_exposure is not None:
            current_market_value = portfolio.market_value_at(market_prices)
            allowed = rule.max_total_exposure * total_equity - current_market_value
            capped_value = self._cap_portfolio_risk_value(
                capped_value,
                allowed,
                stats,
                scaled_key="portfolio_risk_total_exposure_scaled",
                blocked_key="portfolio_risk_total_exposure_blocked",
            )
            if capped_value <= 0:
                return 0.0

        if is_high_vol and rule.max_high_vol_exposure is not None:
            high_value = self._portfolio_group_market_value(
                portfolio,
                market_prices,
                volatility_group="high_vol",
            )
            allowed = rule.max_high_vol_exposure * total_equity - high_value
            capped_value = self._cap_portfolio_risk_value(
                capped_value,
                allowed,
                stats,
                scaled_key="portfolio_risk_high_vol_exposure_scaled",
                blocked_key="portfolio_risk_high_vol_exposure_blocked",
            )

        return max(capped_value, 0.0)

    @staticmethod
    def _cap_portfolio_risk_value(
        value: float,
        allowed: float,
        stats: dict,
        *,
        scaled_key: str,
        blocked_key: str,
    ) -> float:
        if allowed <= 0:
            PortfolioBacktest._record_portfolio_risk_block(stats, blocked_key)
            return 0.0
        if value > allowed:
            stats[scaled_key] = stats.get(scaled_key, 0) + 1
            stats["portfolio_risk_scaled"] = stats.get("portfolio_risk_scaled", 0) + 1
            return allowed
        return value

    @staticmethod
    def _record_portfolio_risk_block(stats: dict, key: str) -> None:
        stats[key] = stats.get(key, 0) + 1
        stats["portfolio_risk_blocked"] = stats.get("portfolio_risk_blocked", 0) + 1

    def _portfolio_group_market_value(
        self,
        portfolio: PortfolioState,
        prices: dict[str, float],
        *,
        volatility_group: str,
    ) -> float:
        return sum(
            pos.shares * prices.get(pos.code, pos.avg_cost)
            for pos in portfolio.positions.values()
            if self.code_volatility_groups.get(pos.code, "unknown_vol") == volatility_group
        )

    def _position_target_budget(
        self,
        max_pos_value: float,
        experiment: AblationExperimentConfig,
        *,
        code: str,
        signal_meta: dict,
    ) -> float:
        """Return the per-position target budget fixed at entry time."""
        multiplier = self._high_vol_quality_budget_multiplier(code, signal_meta, experiment)
        return max_pos_value * multiplier

    def _add_allows_trade(
        self,
        pos: Position,
        exec_price: float,
        signal_meta: dict,
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> bool:
        """Dispatch add validation to budget rules or simple add rules."""
        if experiment.entry_add_budget_rule is not None:
            return self._budget_add_rule_allows_trade(pos, exec_price, signal_meta, experiment, stats)
        return self._add_rule_allows_trade(pos, exec_price, signal_meta, experiment, stats)

    def _budget_add_rule_allows_trade(
        self,
        pos: Position,
        exec_price: float,
        signal_meta: dict,
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> bool:
        """Return whether an add trade passes the entry/add budget rule."""
        rule = experiment.entry_add_budget_rule
        if rule is None or pos.add_count >= len(rule.add_steps):
            stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
            return False

        vol_rule = self._volatility_strategy_rule_for_code(pos.code, experiment)
        has_vol_override = (
            vol_rule is not None
            and (vol_rule.disable_add or pos.add_count < len(vol_rule.min_add_scores))
        )
        if has_vol_override:
            stats["vol_add_candidates"] = stats.get("vol_add_candidates", 0) + 1
            if vol_rule.disable_add:
                stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
                stats["vol_add_blocked"] = stats.get("vol_add_blocked", 0) + 1
                return False

        step = rule.add_steps[pos.add_count]
        if step.require_profit and exec_price <= pos.avg_cost:
            stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
            return False
        min_score = self._volatility_add_min_score(pos.code, pos.add_count, experiment)
        if min_score is None:
            min_score = step.min_score
        if min_score is not None:
            score = signal_meta.get("score")
            if score is None or float(score) < min_score:
                stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
                if has_vol_override:
                    stats["vol_add_blocked"] = stats.get("vol_add_blocked", 0) + 1
                return False
        if has_vol_override:
            stats["vol_add_allowed"] = stats.get("vol_add_allowed", 0) + 1
        if pos.target_budget > 0 and pos.used_budget >= pos.target_budget:
            stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
            return False
        return True

    def _high_vol_quality_allows_entry(
        self,
        advice: dict,
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> bool:
        """Apply high-vol trade-quality filters to new entries."""
        if advice.get("advice") != "建仓":
            return True
        code = advice["code"]
        if not self._high_vol_quality_rule_applies_to_code(code, experiment):
            return True

        rule = experiment.high_vol_quality_rule
        if rule is None:
            return True

        stats["quality_entry_candidates"] = stats.get("quality_entry_candidates", 0) + 1
        signal_meta = advice.get("signal_meta", {}) or {}
        if not self._high_vol_quality_signal_passes(
            signal_meta,
            min_score=rule.min_entry_score,
            min_macd=rule.min_entry_macd,
            min_rsi=rule.min_entry_rsi,
        ):
            stats["quality_entry_blocked"] = stats.get("quality_entry_blocked", 0) + 1
            return False

        stats["quality_entry_allowed"] = stats.get("quality_entry_allowed", 0) + 1
        return True

    def _high_vol_quality_allows_add(
        self,
        code: str,
        signal_meta: dict,
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> bool:
        """Apply high-vol trade-quality filters to adds."""
        if not self._high_vol_quality_rule_applies_to_code(code, experiment):
            return True

        rule = experiment.high_vol_quality_rule
        if rule is None or (rule.min_add_score is None and rule.min_add_macd is None):
            return True

        stats["quality_add_candidates"] = stats.get("quality_add_candidates", 0) + 1
        if not self._high_vol_quality_signal_passes(
            signal_meta,
            min_score=rule.min_add_score,
            min_macd=rule.min_add_macd,
            min_rsi=None,
        ):
            stats["quality_add_blocked"] = stats.get("quality_add_blocked", 0) + 1
            return False

        stats["quality_add_allowed"] = stats.get("quality_add_allowed", 0) + 1
        return True

    def _apply_high_vol_quality_daily_limit(
        self,
        executable: list[dict],
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> list[dict]:
        """Keep the highest-quality high-vol entries when a daily limit is configured."""
        rule = experiment.high_vol_quality_rule
        if rule is None or rule.daily_entry_limit is None:
            return executable

        high_vol_entries = [
            adv for adv in executable
            if adv.get("advice") == "建仓"
            and self._high_vol_quality_rule_applies_to_code(adv["code"], experiment)
        ]
        high_vol_entry_ids = {id(adv) for adv in high_vol_entries}
        limit = rule.daily_entry_limit
        if len(high_vol_entries) <= limit:
            return executable

        ranked = sorted(
            high_vol_entries,
            key=lambda adv: self._high_vol_quality_rank_key(adv.get("signal_meta", {}) or {}),
            reverse=True,
        )
        allowed_ids = {id(adv) for adv in ranked[:limit]}
        filtered = []
        for adv in executable:
            if id(adv) in high_vol_entry_ids and id(adv) not in allowed_ids:
                stats["quality_daily_limit_blocked"] = (
                    stats.get("quality_daily_limit_blocked", 0) + 1
                )
                continue
            filtered.append(adv)
        return filtered

    def _high_vol_quality_budget_multiplier(
        self,
        code: str,
        signal_meta: dict,
        experiment: AblationExperimentConfig,
    ) -> float:
        """Return the target-budget multiplier for high-vol quality tiering."""
        if not self._high_vol_quality_rule_applies_to_code(code, experiment):
            return 1.0

        rule = experiment.high_vol_quality_rule
        if rule is None:
            return 1.0

        score = _as_float(signal_meta.get("score"))
        if (
            rule.strong_entry_score is not None
            and score is not None
            and score >= rule.strong_entry_score
        ):
            return rule.strong_budget_multiplier
        if (
            rule.medium_entry_score is not None
            and score is not None
            and score >= rule.medium_entry_score
        ):
            return rule.medium_budget_multiplier
        if rule.weak_budget_multiplier is not None:
            return rule.weak_budget_multiplier
        return 1.0

    @staticmethod
    def _high_vol_quality_signal_passes(
        signal_meta: dict,
        *,
        min_score: float | None,
        min_macd: float | None,
        min_rsi: float | None,
    ) -> bool:
        """Return whether signal metadata passes configured quality thresholds."""
        score = _as_float(signal_meta.get("score"))
        if min_score is not None and (score is None or score < min_score):
            return False

        macd = _as_float(signal_meta.get("s_macd"))
        if min_macd is not None and (macd is None or macd < min_macd):
            return False

        rsi = _as_float(signal_meta.get("s_rsi"))
        if min_rsi is not None and (rsi is None or rsi < min_rsi):
            return False

        return True

    @staticmethod
    def _high_vol_quality_rank_key(signal_meta: dict) -> tuple[float, float, float]:
        """Rank high-vol entries by score, MACD and RSI components."""
        score = _as_float(signal_meta.get("score"))
        macd = _as_float(signal_meta.get("s_macd"))
        rsi = _as_float(signal_meta.get("s_rsi"))
        return (
            score if score is not None else -999.0,
            macd if macd is not None else -999.0,
            rsi if rsi is not None else -999.0,
        )

    def _add_rule_allows_trade(
        self,
        pos: Position,
        exec_price: float,
        signal_meta: dict,
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> bool:
        """Return whether an add-position trade passes the experiment rule."""
        rule = experiment.add_rule
        vol_rule = self._volatility_strategy_rule_for_code(pos.code, experiment)
        has_vol_override = (
            vol_rule is not None
            and (vol_rule.disable_add or bool(vol_rule.min_add_scores))
        )
        if has_vol_override:
            stats["vol_add_candidates"] = stats.get("vol_add_candidates", 0) + 1
            if vol_rule.disable_add:
                stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
                stats["vol_add_blocked"] = stats.get("vol_add_blocked", 0) + 1
                return False
        if rule.disabled:
            stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
            return False
        if rule.require_profit and exec_price <= pos.avg_cost:
            stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
            return False
        min_score = self._volatility_add_min_score(pos.code, 0, experiment)
        if min_score is None:
            min_score = rule.min_score
        if min_score is not None:
            score = signal_meta.get("score")
            if score is None or float(score) < min_score:
                stats["add_rule_blocked"] = stats.get("add_rule_blocked", 0) + 1
                if has_vol_override:
                    stats["vol_add_blocked"] = stats.get("vol_add_blocked", 0) + 1
                return False
        if has_vol_override:
            stats["vol_add_allowed"] = stats.get("vol_add_allowed", 0) + 1
        return True

    def _volatility_entry_allows_advice(
        self,
        advice: dict,
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> bool:
        """Apply volatility-scoped entry score filters before scheduling trades."""
        if advice.get("advice") != "建仓":
            return True
        code = advice["code"]
        rule = self._volatility_strategy_rule_for_code(code, experiment)
        if rule is None or rule.min_entry_score is None:
            return True

        stats["vol_entry_candidates"] = stats.get("vol_entry_candidates", 0) + 1
        signal_meta = advice.get("signal_meta", {}) or {}
        score = signal_meta.get("score")
        if score is None or float(score) < rule.min_entry_score:
            stats["vol_entry_blocked"] = stats.get("vol_entry_blocked", 0) + 1
            return False

        stats["vol_entry_allowed"] = stats.get("vol_entry_allowed", 0) + 1
        return True

    def _volatility_add_min_score(
        self,
        code: str,
        add_count: int,
        experiment: AblationExperimentConfig,
    ) -> float | None:
        """Return volatility-scoped add score override for the next add step."""
        rule = self._volatility_strategy_rule_for_code(code, experiment)
        if rule is None or add_count >= len(rule.min_add_scores):
            return None
        return rule.min_add_scores[add_count]

    def _volatility_strategy_rule_for_code(
        self,
        code: str,
        experiment: AblationExperimentConfig,
    ) -> VolatilityStrategyRuleConfig | None:
        """Return the first volatility strategy rule that applies to this ETF."""
        for rule in experiment.volatility_strategy_rules:
            if rule.volatility_groups:
                volatility_group = self.code_volatility_groups.get(code, "unknown_vol")
                if volatility_group not in rule.volatility_groups:
                    continue
            if rule.regime_groups:
                regime_group = self.code_regime_groups.get(code, "A股")
                if regime_group not in rule.regime_groups:
                    continue
            return rule
        return None

    def _high_vol_frequency_rule_applies_to_code(
        self,
        code: str,
        experiment: AblationExperimentConfig,
    ) -> bool:
        """Return whether the high-vol frequency rule should affect this ETF."""
        if experiment.high_vol_frequency_rule is None:
            return False
        return self.code_volatility_groups.get(code, "unknown_vol") == "high_vol"

    def _high_vol_quality_rule_applies_to_code(
        self,
        code: str,
        experiment: AblationExperimentConfig,
    ) -> bool:
        """Return whether the high-vol quality rule should affect this ETF."""
        if experiment.high_vol_quality_rule is None:
            return False
        return self.code_volatility_groups.get(code, "unknown_vol") == "high_vol"

    @staticmethod
    def _cap_add_shares(
        requested_shares: int,
        pos: Position,
        experiment: AblationExperimentConfig,
        stats: dict,
    ) -> int:
        """Apply add-position share caps from the experiment rule."""
        ratio = experiment.add_rule.max_add_to_current_ratio
        if experiment.entry_add_budget_rule is not None:
            ratio = 1.0
        if ratio is None:
            return requested_shares
        max_shares = int((pos.shares * ratio) / 100) * 100
        if max_shares <= 0:
            return 0
        if requested_shares > max_shares:
            stats["add_rule_scaled"] = stats.get("add_rule_scaled", 0) + 1
            return int(max_shares)
        return requested_shares

    # ── 风控检查 ──

    def _check_risk(
        self,
        portfolio: PortfolioState,
        price_map: dict[str, dict[str, float]],
        day_str: str,
        use_stop_loss: bool = True,
        max_holding_days: int | None = None,
        experiment: AblationExperimentConfig | None = None,
        risk_data: dict[str, dict] | None = None,
    ) -> dict[str, dict]:
        """检查持仓是否需要止损/止盈。

        简化版：持仓超过 8% 亏损直接触发卖出。
        """
        risk_signals: dict[str, dict] = {}
        day_date = date.fromisoformat(day_str)
        risk_data = risk_data or {}
        for code, pos in portfolio.positions.items():
            close = price_map.get(code, {}).get(day_str)
            if close is None:
                continue
            if (
                max_holding_days is not None
                and pos.entry_date is not None
                and (day_date - pos.entry_date).days >= max_holding_days
            ):
                risk_signals[code] = {
                    "signal": "SELL",
                    "source": "max_holding",
                    "reason": f"max_holding:{max_holding_days}d",
                }
                continue
            if not use_stop_loss:
                continue
            pnl_pct = (close - pos.avg_cost) / pos.avg_cost
            experimental_signal = self._experimental_risk_signal(
                pos=pos,
                close=close,
                pnl_pct=pnl_pct,
                experiment=experiment,
                risk_info=risk_data.get(code, {}),
            )
            if experimental_signal is not None:
                risk_signals[code] = experimental_signal
                continue
            threshold = self._stop_loss_threshold(
                experiment=experiment,
                risk_info=risk_data.get(code, {}),
                stop_loss_profile=self.code_stop_loss_profiles.get(code),
                high_vol_frequency_rule=(
                    experiment.high_vol_frequency_rule
                    if experiment is not None
                    and self._high_vol_frequency_rule_applies_to_code(code, experiment)
                    else None
                ),
                high_vol_quality_rule=(
                    experiment.high_vol_quality_rule
                    if experiment is not None
                    and self._high_vol_quality_rule_applies_to_code(code, experiment)
                    else None
                ),
            )
            if threshold is None:
                continue
            if pnl_pct <= threshold:
                profile = self.code_stop_loss_profiles.get(code)
                risk_signals[code] = {
                    "signal": "SELL",
                    "source": "stop_loss",
                    "reason": f"stop_loss:{threshold:.2%}",
                    "stop_loss_profile": profile,
                }
        return risk_signals

    @staticmethod
    def _experimental_risk_signal(
        *,
        pos: Position,
        close: float,
        pnl_pct: float,
        experiment: AblationExperimentConfig | None,
        risk_info: dict,
    ) -> dict[str, str] | None:
        """Return a backtest-only risk signal from an experimental risk profile."""
        profile = experiment.experimental_risk_profile if experiment is not None else None
        if profile is None:
            return None

        atr_pct = _as_float(risk_info.get("atr_pct"))
        ma20 = _as_float(risk_info.get("ma20"))
        ma60 = _as_float(risk_info.get("ma60"))
        dif = _as_float(risk_info.get("dif"))
        dea = _as_float(risk_info.get("dea"))

        if profile.kind == "high_vol_trend":
            threshold = _bounded_negative_atr_threshold(
                atr_pct,
                mult=2.5,
                tight=-0.08,
                loose=-0.15,
            )
            if threshold is not None and pnl_pct <= threshold:
                return {
                    "signal": "SELL",
                    "source": "stop_loss",
                    "reason": f"high_vol_atr_stop:{threshold:.2%}",
                }

            peak = pos.peak_price or close
            peak_pnl = (peak - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0.0
            if peak_pnl >= 0.08 and atr_pct is not None:
                trailing_stop = peak * (1 - 2.2 * atr_pct)
                if close <= trailing_stop:
                    return {
                        "signal": "SELL",
                        "source": "trailing_stop",
                        "reason": "high_vol_atr_trailing_stop",
                    }

            if ma20 is not None and dif is not None and dea is not None:
                if close < ma20 and dif < dea:
                    return {
                        "signal": "SELL",
                        "source": "trend_exit",
                        "reason": "high_vol_ma20_macd_break",
                    }

        if profile.kind == "low_vol_structure":
            if pnl_pct <= -0.12:
                return {
                    "signal": "SELL",
                    "source": "disaster_stop",
                    "reason": "low_vol_disaster_stop:-12%",
                }
            if ma20 is not None and ma60 is not None and dif is not None and dea is not None:
                if close < ma60 and ma20 < ma60 and dif < dea:
                    return {
                        "signal": "SELL",
                        "source": "structure_exit",
                        "reason": "low_vol_ma60_structure_break",
                    }

        return None

    @staticmethod
    def _stop_loss_threshold(
        experiment: AblationExperimentConfig | None,
        risk_info: dict,
        stop_loss_profile: str | None = None,
        high_vol_frequency_rule: HighVolFrequencyControlRuleConfig | None = None,
        high_vol_quality_rule: HighVolQualityControlRuleConfig | None = None,
    ) -> float | None:
        """Return the active stop-loss threshold for an experiment."""
        if (
            high_vol_frequency_rule is not None
            and high_vol_frequency_rule.high_vol_stop_loss_threshold is not None
        ):
            return high_vol_frequency_rule.high_vol_stop_loss_threshold
        if (
            high_vol_quality_rule is not None
            and high_vol_quality_rule.high_vol_stop_loss_threshold is not None
        ):
            return high_vol_quality_rule.high_vol_stop_loss_threshold
        rule = experiment.stop_loss_rule if experiment is not None else None
        if experiment is not None and experiment.use_config_stop_loss_profiles:
            rule = stop_loss_rule_from_profile(stop_loss_profile)
        if rule is None:
            return -0.08
        if rule.kind == "none":
            return None
        if rule.kind == "fixed":
            return rule.threshold if rule.threshold is not None else -0.08
        if rule.kind == "atr":
            atr_pct = risk_info.get("atr_pct")
            if atr_pct is None or rule.atr_mult is None:
                return None
            threshold = -float(atr_pct) * rule.atr_mult
            if rule.min_threshold is not None:
                threshold = max(threshold, rule.min_threshold)
            if rule.max_threshold is not None:
                threshold = min(threshold, rule.max_threshold)
            return threshold
        return -0.08

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
    code_regime_groups = {e.symbol: e.regime_group for e in config.etf_list}

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
        market_regime_params=config.market_regime_params,
        code_regime_groups=code_regime_groups,
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


def _as_float(value: Any) -> float | None:
    """Convert indicator values to float while treating missing values as unavailable."""
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _bounded_negative_atr_threshold(
    atr_pct: float | None,
    *,
    mult: float,
    tight: float,
    loose: float,
) -> float | None:
    """Return a negative ATR stop threshold bounded by tight/loose limits."""
    if atr_pct is None:
        return None
    threshold = -float(atr_pct) * mult
    threshold = max(threshold, loose)
    threshold = min(threshold, tight)
    return threshold
