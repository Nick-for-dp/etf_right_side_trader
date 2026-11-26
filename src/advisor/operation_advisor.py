"""操作建议生成器：信号 × 持仓 × 门控 → 建议。

优先级：风控 > 市场状态（RISK_OFF）> 加仓冷却 > 阶梯加仓 > 技术信号。
实盘（daily_runner）与回测（portfolio_backtest）调用同一份实现。
"""

from datetime import date

import pandas as pd

from src.models import AdviceAction, MarketState, SignalSource, SignalType

# 建议映射表：key = (has_position, signal)
_ADVICE_MAP = {
    (False, SignalType.BUY): AdviceAction.OPEN,
    (False, SignalType.HOLD): AdviceAction.WATCH,
    (False, SignalType.SELL): AdviceAction.NO_OP,
    (True,  SignalType.BUY): AdviceAction.ADD,
    (True,  SignalType.HOLD): AdviceAction.HOLD,
    (True,  SignalType.SELL): AdviceAction.SELL,
}

# 买入类建议被门控时的降级动作。
_BUY_OVERRIDE = {
    AdviceAction.OPEN: AdviceAction.WATCH,
    AdviceAction.ADD: AdviceAction.HOLD,
}

_MARKET_BLOCK_STATES = {MarketState.RISK_OFF.value}


def generate_advice(positions: list[dict],
                    signals: pd.DataFrame,
                    current_prices: dict[str, float],
                    risk_signals: dict[str, dict] | None = None,
                    market_regime: dict | None = None,
                    last_buy_dates: dict[str, date] | None = None,
                    add_counts: dict[str, int] | None = None,
                    entry_add_budget: dict | None = None,
                    entry_budget_overrides: dict | None = None,
                    code_volatility_groups: dict[str, str] | None = None,
                    stop_loss_profiles: dict[str, str] | None = None,
                    add_cooldown_days: int = 0,
                    account_capital: float | None = None,
                    max_position_ratio: float = 0.30) -> list[dict]:
    """交叉持仓、信号与门控，返回操作建议列表。

    Args:
        positions: 持仓列表，每项含 id、code、cost、shares、entry_date
        signals: 信号 DataFrame，columns = [code, date, signal, signal_meta]
        current_prices: {code: close_price} 当前价格映射
        risk_signals: {code: {"signal": "SELL", "source": "stop_loss", "reason": ...}}，风控覆盖
        market_regime: {code: {"state": "NORMAL", "score": 0.1, "data": {...}}} 分市场状态
        last_buy_dates: {code: date} 最近一次真实建仓/加仓日期
        add_counts: {code: int} 本轮持仓已完成加仓次数
        entry_add_budget: 70/15/15 等执行预算拆分参数
        entry_budget_overrides: 按波动组调整目标预算的规则
        code_volatility_groups: {code: volatility_group}，用于按波动组应用预算覆盖
        stop_loss_profiles: {code: stop_loss_profile} ETF 止损 profile
        add_cooldown_days: 加仓冷却天数，0 表示不启用
        account_capital: 账户总资金；提供时在 advice_meta.execution 写入可执行金额与股数
        max_position_ratio: 单 ETF 仓位上限，占账户比例

    Returns:
        操作建议列表，每项含 code、date、position_id、cost、pnl_pct、signal、advice、
        signal_source、target_budget_ratio、entry_add_step、score、market_state、
        stop_loss_profile、blocked_reason、advice_meta

    Example:
        >>> advices = generate_advice(
        ...     positions=[{"id": 1, "code": "588000", "cost": 1.0, "shares": 1000, "entry_date": "2026-04-01"}],
        ...     signals=pd.DataFrame([{"code": "588000", "date": "2026-04-28", "signal": "SELL", "signal_meta": {}}]),
        ...     current_prices={"588000": 1.05},
        ... )
        >>> advices[0]["advice"]
        '卖出'
    """
    risk_signals = risk_signals or {}
    market_regime = market_regime or {}
    last_buy_dates = last_buy_dates or {}
    add_counts = add_counts or {}
    entry_add_budget = entry_add_budget or {}
    entry_budget_overrides = entry_budget_overrides or {}
    code_volatility_groups = code_volatility_groups or {}
    stop_loss_profiles = stop_loss_profiles or {}
    pos_map = {p["code"]: p for p in positions}

    results = []
    for _, row in signals.iterrows():
        code = row["code"]
        has_pos = code in pos_map
        signal_meta = row.get("signal_meta", {}) or {}
        score = _to_float(signal_meta.get("score"))
        regime_for_code = _regime_for_code(code, market_regime)
        market_state = regime_for_code.get("state", "NORMAL")
        stop_loss_profile = stop_loss_profiles.get(code)
        add_count = add_counts.get(code, 0)

        # ── 优先级 1：风控覆盖 ──
        if code in risk_signals:
            rs = risk_signals[code]
            advice = _ADVICE_MAP.get((True, SignalType.SELL), AdviceAction.SELL)
            pos = pos_map[code]
            price = current_prices.get(code)
            pnl_pct = (price - pos["cost"]) / pos["cost"] if price else None
            advice_meta = _build_advice_meta(
                raw_advice=advice,
                final_advice=advice,
                has_position=True,
                signal_meta=signal_meta,
                market_regime=regime_for_code,
                add_count=add_count,
                budget=entry_add_budget,
                budget_override_rule=None,
                stop_loss_profile=stop_loss_profile,
                risk_reason=rs.get("reason"),
            )
            advice_meta["execution"] = _execution_plan(
                advice=advice,
                budget_plan=None,
                price=price,
                position=pos,
                capital=account_capital,
                max_position_ratio=max_position_ratio,
            )
            results.append({
                "code": code,
                "date": str(row["date"]),
                "position_id": pos["id"],
                "cost": pos["cost"],
                "pnl_pct": round(pnl_pct, 6) if pnl_pct is not None else None,
                "signal": SignalType.SELL.value,
                "advice": advice.value,
                "signal_source": rs["source"],
                "target_position_ratio": None,
                "target_budget_ratio": None,
                "entry_add_step": None,
                "score": score,
                "market_state": market_state,
                "stop_loss_profile": rs.get("stop_loss_profile", stop_loss_profile),
                "blocked_reason": rs.get("reason"),
                "advice_meta": advice_meta,
            })
            continue

        signal = SignalType(row["signal"])
        raw_advice = _ADVICE_MAP.get((has_pos, signal), AdviceAction.WATCH)
        advice = raw_advice
        signal_source = SignalSource.TREND
        blocked_reason = None

        # ── 优先级 2：市场状态门控（按 ETF 的 regime_group 区分市场）──
        if advice in _BUY_OVERRIDE and market_state in _MARKET_BLOCK_STATES:
            advice = _BUY_OVERRIDE[advice]
            signal_source = SignalSource.MARKET_REGIME
            blocked_reason = f"market_regime:{market_state}"

        # ── 优先级 3：加仓冷却 ──
        # 只限制加仓频率，不影响建仓、SELL、HOLD 和风控覆盖。
        if advice == AdviceAction.ADD and add_cooldown_days > 0:
            last_buy_date = last_buy_dates.get(code)
            signal_date = _parse_date(row["date"])
            if last_buy_date is not None and signal_date is not None:
                days_since_buy = (signal_date - last_buy_date).days
                if 0 <= days_since_buy < add_cooldown_days:
                    advice = AdviceAction.HOLD
                    signal_source = SignalSource.ADD_COOLDOWN
                    blocked_reason = (
                        f"add_cooldown:{days_since_buy}/{add_cooldown_days}"
                    )

        # ── 优先级 4：70/15/15 阶梯加仓门控 ──
        if advice == AdviceAction.ADD:
            pos = pos_map.get(code)
            current_price = current_prices.get(code)
            allowed, reason = _add_budget_check(
                position=pos,
                current_price=current_price,
                signal_meta=signal_meta,
                add_count=add_count,
                budget=entry_add_budget,
            )
            if not allowed:
                advice = AdviceAction.HOLD
                signal_source = SignalSource.ADD_BUDGET
                blocked_reason = reason

        budget_override_rule = _budget_override_rule_for_code(
            code,
            code_volatility_groups,
            entry_budget_overrides,
        )
        budget_plan = _budget_plan(
            raw_advice,
            add_count,
            entry_add_budget,
            signal_meta=signal_meta,
            budget_override_rule=budget_override_rule,
        )
        advice_meta = _build_advice_meta(
            raw_advice=raw_advice,
            final_advice=advice,
            has_position=has_pos,
            signal_meta=signal_meta,
            market_regime=regime_for_code,
            add_count=add_count,
            budget=entry_add_budget,
            budget_override_rule=budget_override_rule,
            stop_loss_profile=stop_loss_profile,
            blocked_reason=blocked_reason,
            budget_plan=budget_plan,
        )

        pos = pos_map.get(code)
        price = current_prices.get(code)
        pnl_pct = None
        if pos is not None and price:
            pnl_pct = round((price - pos["cost"]) / pos["cost"], 6)

        advice_meta["execution"] = _execution_plan(
            advice=advice,
            budget_plan=budget_plan,
            price=price,
            position=pos,
            capital=account_capital,
            max_position_ratio=max_position_ratio,
        )

        results.append({
            "code": code,
            "date": str(row["date"]),
            "position_id": pos["id"] if pos is not None else None,
            "cost": pos["cost"] if pos is not None else None,
            "pnl_pct": pnl_pct,
            "signal": signal.value,
            "advice": advice.value,
            "signal_source": signal_source.value,
            "target_position_ratio": budget_plan.get("target_position_ratio"),
            "target_budget_ratio": budget_plan.get("target_budget_ratio"),
            "entry_add_step": budget_plan.get("entry_add_step"),
            "score": score,
            "market_state": market_state,
            "stop_loss_profile": stop_loss_profile,
            "blocked_reason": blocked_reason,
            "advice_meta": advice_meta,
        })

    return results


def _parse_date(value) -> date | None:
    """解析 DataFrame 中的日期值。"""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _regime_for_code(code: str, market_regime: dict) -> dict:
    """Return the market regime snapshot for one ETF code."""
    if code in market_regime:
        return market_regime[code]
    if isinstance(market_regime, dict) and "state" in market_regime:
        return market_regime
    return {"state": "NORMAL"}


def _to_float(value) -> float | None:
    """Convert a value to float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _budget_plan(
    raw_advice: AdviceAction,
    add_count: int,
    budget: dict,
    *,
    signal_meta: dict | None = None,
    budget_override_rule: dict | None = None,
) -> dict:
    """Build the target budget metadata for entry/add advice."""
    base_entry_ratio = _to_float(budget.get("entry_ratio")) or 1.0
    multiplier, override_meta = _entry_budget_multiplier(
        signal_meta or {},
        budget_override_rule,
    )
    entry_ratio = base_entry_ratio * multiplier
    steps = budget.get("add_steps", [])

    if raw_advice == AdviceAction.OPEN:
        return {
            "stage": "entry",
            "target_budget_ratio": entry_ratio,
            "target_position_ratio": entry_ratio,
            "entry_add_step": None,
            **override_meta,
        }

    if raw_advice != AdviceAction.ADD or add_count >= len(steps):
        return {}

    step = steps[add_count]
    step_ratio = _to_float(step.get("ratio"))
    if step_ratio is None:
        return {}
    completed_add_ratio = sum(
        _to_float(item.get("ratio")) or 0.0
        for item in steps[:add_count]
    )
    return {
        "stage": "add",
        "target_budget_ratio": step_ratio * multiplier,
        "target_position_ratio": (
            base_entry_ratio + completed_add_ratio + step_ratio
        ) * multiplier,
        "entry_add_step": add_count + 1,
        "require_profit": step.get("require_profit", True),
        "min_score": step.get("min_score"),
        **override_meta,
    }


def _budget_override_rule_for_code(
    code: str,
    code_volatility_groups: dict[str, str],
    entry_budget_overrides: dict,
) -> dict | None:
    group = code_volatility_groups.get(code, "unknown_vol")
    rule = entry_budget_overrides.get(group)
    if not rule or not rule.get("enabled", False):
        return None
    return rule


def _entry_budget_multiplier(signal_meta: dict, rule: dict | None) -> tuple[float, dict]:
    if rule is None or rule.get("kind") != "quality_tier":
        return 1.0, {}
    score = _to_float(signal_meta.get("score"))
    if score is None:
        return 1.0, {
            "budget_override_kind": "quality_tier",
            "budget_quality_tier": "unknown",
            "budget_multiplier": 1.0,
        }

    strong_score = _to_float(rule.get("strong_score")) or 65.0
    medium_score = _to_float(rule.get("medium_score")) or 55.0
    if score >= strong_score:
        tier = "strong"
        multiplier = _to_float(rule.get("strong_multiplier")) or 1.0
    elif score >= medium_score:
        tier = "medium"
        multiplier = _to_float(rule.get("medium_multiplier")) or 0.80
    else:
        tier = "weak"
        multiplier = _to_float(rule.get("weak_multiplier")) or 0.60

    return multiplier, {
        "budget_override_kind": "quality_tier",
        "budget_quality_tier": tier,
        "budget_multiplier": multiplier,
    }


def _execution_plan(
    advice: AdviceAction,
    budget_plan: dict | None,
    price: float | None,
    position: dict | None,
    capital: float | None,
    max_position_ratio: float,
) -> dict:
    """把预算比例翻译成可执行的金额、参考股数与账户占比。

    不提供 account_capital 时返回空 dict（回测自己算仓位，不重复换算）。
    """
    if not capital or not price or price <= 0:
        return {}

    if advice == AdviceAction.SELL:
        shares = int(position["shares"]) if position else 0
        return {
            "shares": shares,
            "amount": round(shares * price, 2),
            "position_ratio": 0.0,
            "lot_size": 100,
        }

    if advice not in (AdviceAction.OPEN, AdviceAction.ADD):
        return {}

    target_budget_ratio = _to_float((budget_plan or {}).get("target_budget_ratio"))
    if target_budget_ratio is None:
        return {}

    amount = capital * max_position_ratio * target_budget_ratio
    shares = int(amount // (price * 100)) * 100
    held_shares = int(position["shares"]) if position else 0
    position_ratio = (held_shares * price + shares * price) / capital
    return {
        "shares": shares,
        "amount": round(amount, 2),
        "position_ratio": round(position_ratio, 4),
        "lot_size": 100,
    }


def _build_advice_meta(
    raw_advice: AdviceAction,
    final_advice: AdviceAction,
    has_position: bool,
    signal_meta: dict,
    market_regime: dict,
    add_count: int,
    budget: dict,
    budget_override_rule: dict | None,
    stop_loss_profile: str | None,
    blocked_reason: str | None = None,
    budget_plan: dict | None = None,
    risk_reason: str | None = None,
) -> dict:
    """Build JSON metadata used by Dashboard explanations."""
    return {
        "raw_advice": raw_advice.value,
        "final_advice": final_advice.value,
        "has_position": has_position,
        "score": _to_float(signal_meta.get("score")),
        "signal_meta": signal_meta,
        "market_state": market_regime.get("state", "NORMAL"),
        "market_score": market_regime.get("score"),
        "stop_loss_profile": stop_loss_profile,
        "add_count": add_count,
        "entry_add_budget": {
            "entry_ratio": _to_float(budget.get("entry_ratio")),
            "add_steps": budget.get("add_steps", []),
        },
        "entry_budget_override": budget_override_rule or {},
        "budget_plan": budget_plan or {},
        "blocked_reason": blocked_reason,
        "risk_reason": risk_reason,
    }


def _add_budget_check(
    position: dict | None,
    current_price: float | None,
    signal_meta: dict,
    add_count: int,
    budget: dict,
) -> tuple[bool, str | None]:
    """Return whether the next configured add step is allowed and why."""
    steps = budget.get("add_steps", [])
    if not steps:
        return True, None
    if position is None or current_price is None:
        return False, "add_budget:missing_position_or_price"
    if add_count >= len(steps):
        return False, "add_budget:steps_used"

    step = steps[add_count]
    if step.get("require_profit", True):
        cost = position.get("cost")
        if cost is None or current_price <= float(cost):
            return False, "add_budget:not_profitable"

    min_score = step.get("min_score")
    score = _to_float(signal_meta.get("score"))
    if min_score is not None and (score is None or score < float(min_score)):
        return False, f"add_budget:score_below_{min_score}"

    return True, None
