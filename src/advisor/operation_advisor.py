"""操作建议生成器：信号 × 持仓 × 门控 → 建议。

v2.4 gate-lite：仅高溢价和极端市场下行状态硬拦截买入类建议。
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

_MARKET_BLOCK_STATES = {
    MarketState.HOT_FALLING.value,
    MarketState.BEAR_TREND.value,
    MarketState.PANIC.value,
}


def generate_advice(positions: list[dict],
                    signals: pd.DataFrame,
                    current_prices: dict[str, float],
                    risk_signals: dict[str, dict] | None = None,
                    odds_map: dict[str, dict] | None = None,
                    market_regime: dict | None = None,
                    last_buy_dates: dict[str, date] | None = None,
                    add_counts: dict[str, int] | None = None,
                    entry_add_budget: dict | None = None,
                    add_cooldown_days: int = 0,
                    use_premium_gate: bool = True,
                    use_market_gate: bool = True,
                    use_add_cooldown: bool = True,
                    use_add_budget: bool = True) -> list[dict]:
    """交叉持仓、信号与赔率门控，返回操作建议列表。

    优先级：风控 > 高溢价门控 > 极端市场门控 > 加仓冷却 > 技术信号

    Args:
        positions: 持仓列表，每项含 id、code、cost、shares、entry_date
        signals: 信号 DataFrame，columns = [code, date, signal, signal_meta]
        current_prices: {code: close_price} 当前价格映射
        risk_signals: {code: {"signal": "SELL", "source": "stop_loss"}}，风控覆盖
        odds_map: {code: {"odds_state": "FAIR", "odds_score": 15.2, "premium_blocked": False}}
        market_regime: {"state": "NORMAL", "score": 0.1, "data": {...}}
        last_buy_dates: {code: date} 最近一次真实建仓/加仓日期
        add_counts: {code: int} 已执行加仓次数
        entry_add_budget: 70/15/15 等执行预算拆分参数
        add_cooldown_days: 加仓冷却天数，0 表示不启用
        use_premium_gate: 是否启用高溢价硬门控
        use_market_gate: 是否启用 gate-lite 市场门控
        use_add_cooldown: 是否启用加仓冷却
        use_add_budget: 是否启用阶梯加仓门控

    Returns:
        操作建议列表，每项含 code、date、position_id、cost、pnl_pct、signal、advice、signal_source

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
    odds_map = odds_map or {}
    market_regime = market_regime or {}
    last_buy_dates = last_buy_dates or {}
    add_counts = add_counts or {}
    entry_add_budget = entry_add_budget or {}
    pos_map = {p["code"]: p for p in positions}

    results = []
    for _, row in signals.iterrows():
        code = row["code"]
        has_pos = code in pos_map
        odds = odds_map.get(code, {})

        # ── 优先级 1：风控覆盖 ──
        if code in risk_signals:
            rs = risk_signals[code]
            advice = _ADVICE_MAP.get((True, SignalType.SELL), AdviceAction.SELL)
            pos = pos_map[code]
            price = current_prices.get(code)
            pnl_pct = (price - pos["cost"]) / pos["cost"] if price else None
            results.append({
                "code": code,
                "date": str(row["date"]),
                "position_id": pos["id"],
                "cost": pos["cost"],
                "pnl_pct": round(pnl_pct, 6) if pnl_pct is not None else None,
                "signal": SignalType.SELL.value,
                "advice": advice.value,
                "signal_source": rs["source"],
            })
            continue

        signal = SignalType(row["signal"])
        advice = _ADVICE_MAP.get((has_pos, signal), AdviceAction.WATCH)
        signal_source = SignalSource.TREND

        # ── 优先级 2：高溢价硬门控 ──
        # gate-lite 不再因 EXPENSIVE 赔率状态硬拦截买入；只保留高溢价硬过滤。
        premium_blocked = odds.get("premium_blocked", False)
        if use_premium_gate and advice in _BUY_OVERRIDE and premium_blocked:
            advice = _BUY_OVERRIDE[advice]

        # ── 优先级 3：极端市场门控（gate-lite）──
        # 支持按 ETF 的 regime_group 区分市场。
        # market_regime 可以是：
        #   - 单个 dict（全局统一，向后兼容）
        #   - dict of {code: {"state": ...}}（每个 ETF 对应各自市场状态）
        # 只拦截 HOT_FALLING / BEAR_TREND / PANIC。
        if use_market_gate and advice in _BUY_OVERRIDE:
            if code in market_regime:
                regime_for_code = market_regime[code]
            elif isinstance(market_regime, dict) and "state" in market_regime:
                regime_for_code = market_regime
            else:
                regime_for_code = {"state": "NORMAL"}
            market_state = regime_for_code.get("state", "NORMAL")
            if market_state in _MARKET_BLOCK_STATES:
                advice = _BUY_OVERRIDE[advice]
                signal_source = SignalSource.MARKET_REGIME

        # ── 优先级 4：加仓冷却 ──
        # 只限制加仓频率，不影响建仓、SELL、HOLD 和风控覆盖。
        if use_add_cooldown and advice == AdviceAction.ADD and add_cooldown_days > 0:
            last_buy_date = last_buy_dates.get(code)
            signal_date = _parse_date(row["date"])
            if last_buy_date is not None and signal_date is not None:
                days_since_buy = (signal_date - last_buy_date).days
                if 0 <= days_since_buy < add_cooldown_days:
                    advice = AdviceAction.HOLD
                    signal_source = SignalSource.ADD_COOLDOWN

        # ── 优先级 5：70/15/15 阶梯加仓门控 ──
        # 只限制加仓建议；建仓比例和具体金额由人工执行层按预算口径处理。
        if use_add_budget and advice == AdviceAction.ADD:
            pos = pos_map.get(code)
            current_price = current_prices.get(code)
            if not _add_budget_allows(
                position=pos,
                current_price=current_price,
                signal_meta=row.get("signal_meta", {}) or {},
                add_count=add_counts.get(code, 0),
                budget=entry_add_budget,
            ):
                advice = AdviceAction.HOLD
                signal_source = SignalSource.ADD_BUDGET

        if has_pos:
            pos = pos_map[code]
            price = current_prices.get(code)
            pnl_pct = (price - pos["cost"]) / pos["cost"] if price else None
            results.append({
                "code": code,
                "date": str(row["date"]),
                "position_id": pos["id"],
                "cost": pos["cost"],
                "pnl_pct": round(pnl_pct, 6) if pnl_pct is not None else None,
                "signal": signal.value,
                "advice": advice.value,
                "signal_source": signal_source.value,
            })
        else:
            results.append({
                "code": code,
                "date": str(row["date"]),
                "position_id": None,
                "cost": None,
                "pnl_pct": None,
                "signal": signal.value,
                "advice": advice.value,
                "signal_source": signal_source.value,
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


def _add_budget_allows(
    position: dict | None,
    current_price: float | None,
    signal_meta: dict,
    add_count: int,
    budget: dict,
) -> bool:
    """Return whether the next configured add step is allowed."""
    steps = budget.get("add_steps", [])
    if not steps:
        return True
    if position is None or current_price is None:
        return False
    if add_count >= len(steps):
        return False

    step = steps[add_count]
    if step.get("require_profit", True):
        cost = position.get("cost")
        if cost is None or current_price <= float(cost):
            return False

    min_score = step.get("min_score")
    score = signal_meta.get("score")
    if min_score is not None and (score is None or float(score) < float(min_score)):
        return False

    return True
