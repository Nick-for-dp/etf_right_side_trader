"""操作建议生成器：信号 × 持仓 × 门控 → 建议。

v2.1A：新增长期赔率门控，EXPENSIVE 或高溢价时拦截买入，不影响卖出。
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

# 赔率门控覆盖：长期赔率偏贵或高溢价时，禁止新开仓和加仓
_ODDS_OVERRIDE = {
    AdviceAction.OPEN: AdviceAction.WATCH,
    AdviceAction.ADD: AdviceAction.HOLD,
}


def generate_advice(positions: list[dict],
                    signals: pd.DataFrame,
                    current_prices: dict[str, float],
                    risk_signals: dict[str, dict] | None = None,
                    odds_map: dict[str, dict] | None = None,
                    market_regime: dict | None = None,
                    last_buy_dates: dict[str, date] | None = None,
                    add_cooldown_days: int = 0) -> list[dict]:
    """交叉持仓、信号与赔率门控，返回操作建议列表。

    优先级：风控 > 赔率门控 > 市场热度门控 > 加仓冷却 > 技术信号

    Args:
        positions: 持仓列表，每项含 id、code、cost、shares、entry_date
        signals: 信号 DataFrame，columns = [code, date, signal, signal_meta]
        current_prices: {code: close_price} 当前价格映射
        risk_signals: {code: {"signal": "SELL", "source": "stop_loss"}}，风控覆盖
        odds_map: {code: {"odds_state": "FAIR", "odds_score": 15.2, "premium_blocked": False}}
        market_regime: {"state": "NORMAL", "score": 0.1, "data": {...}}
        last_buy_dates: {code: date} 最近一次真实建仓/加仓日期
        add_cooldown_days: 加仓冷却天数，0 表示不启用

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

        # ── 优先级 2：长期赔率门控（v2.1A） ──
        # 仅拦截买入类操作（建仓/加仓），SELL 和 HOLD 不受影响
        odds_state = odds.get("odds_state")
        premium_blocked = odds.get("premium_blocked", False)
        if advice in _ODDS_OVERRIDE:
            if odds_state == "EXPENSIVE" or premium_blocked:
                advice = _ODDS_OVERRIDE[advice]

        # ── 优先级 3：市场热度门控（v2.2）──
        # HOT 避免追高，COLD 避免弱反弹；UNKNOWN 不拦截。
        if advice in _ODDS_OVERRIDE:
            market_state = market_regime.get("state")
            if market_state in {MarketState.HOT.value, MarketState.COLD.value}:
                advice = _ODDS_OVERRIDE[advice]
                signal_source = SignalSource.MARKET_REGIME

        # ── 优先级 4：加仓冷却 ──
        # 只限制加仓频率，不影响建仓、SELL、HOLD 和风控覆盖。
        if advice == AdviceAction.ADD and add_cooldown_days > 0:
            last_buy_date = last_buy_dates.get(code)
            signal_date = _parse_date(row["date"])
            if last_buy_date is not None and signal_date is not None:
                days_since_buy = (signal_date - last_buy_date).days
                if 0 <= days_since_buy < add_cooldown_days:
                    advice = AdviceAction.HOLD
                    signal_source = SignalSource.ADD_COOLDOWN

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
