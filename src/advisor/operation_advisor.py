"""操作建议生成器：信号 × 持仓 × 赔率门控 → 建议。

v2.1A：新增长期赔率门控，EXPENSIVE 或高溢价时拦截买入，不影响卖出。
"""

import pandas as pd

# 建议映射表：key = (has_position, signal)
_ADVICE_MAP = {
    (False, "BUY"):  "建仓",
    (False, "HOLD"): "观望",
    (False, "SELL"): "不操作",
    (True,  "BUY"):  "加仓",
    (True,  "HOLD"): "继续持有",
    (True,  "SELL"): "卖出",
}

# 赔率门控覆盖：长期赔率偏贵或高溢价时，禁止新开仓和加仓
_ODDS_OVERRIDE = {
    "建仓": "观望",
    "加仓": "继续持有",
}


def generate_advice(positions: list[dict],
                    signals: pd.DataFrame,
                    current_prices: dict[str, float],
                    risk_signals: dict[str, dict] | None = None,
                    odds_map: dict[str, dict] | None = None) -> list[dict]:
    """交叉持仓、信号与赔率门控，返回操作建议列表。

    优先级：风控 > 赔率门控 > 技术信号

    Args:
        positions: 持仓列表，每项含 id、code、cost、shares、entry_date
        signals: 信号 DataFrame，columns = [code, date, signal, signal_meta]
        current_prices: {code: close_price} 当前价格映射
        risk_signals: {code: {"signal": "SELL", "source": "stop_loss"}}，风控覆盖
        odds_map: {code: {"odds_state": "FAIR", "odds_score": 15.2, "premium_blocked": False}}

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
    pos_map = {p["code"]: p for p in positions}

    results = []
    for _, row in signals.iterrows():
        code = row["code"]
        has_pos = code in pos_map
        odds = odds_map.get(code, {})

        # ── 优先级 1：风控覆盖 ──
        if code in risk_signals:
            rs = risk_signals[code]
            advice = _ADVICE_MAP.get((True, "SELL"), "卖出")
            pos = pos_map[code]
            price = current_prices.get(code)
            pnl_pct = (price - pos["cost"]) / pos["cost"] if price else None
            results.append({
                "code": code,
                "date": str(row["date"]),
                "position_id": pos["id"],
                "cost": pos["cost"],
                "pnl_pct": round(pnl_pct, 6) if pnl_pct is not None else None,
                "signal": "SELL",
                "advice": advice,
                "signal_source": rs["source"],
            })
            continue

        signal = row["signal"]
        advice = _ADVICE_MAP.get((has_pos, signal), "观望")

        # ── 优先级 2：长期赔率门控（v2.1A） ──
        # 仅拦截买入类操作（建仓/加仓），SELL 和 HOLD 不受影响
        odds_state = odds.get("odds_state")
        premium_blocked = odds.get("premium_blocked", False)
        if advice in _ODDS_OVERRIDE:
            if odds_state == "EXPENSIVE" or premium_blocked:
                advice = _ODDS_OVERRIDE[advice]

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
                "signal": signal,
                "advice": advice,
                "signal_source": "trend",
            })
        else:
            results.append({
                "code": code,
                "date": str(row["date"]),
                "position_id": None,
                "cost": None,
                "pnl_pct": None,
                "signal": signal,
                "advice": advice,
                "signal_source": "trend",
            })

    return results
