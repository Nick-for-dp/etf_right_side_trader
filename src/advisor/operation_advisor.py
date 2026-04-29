"""操作建议生成器：信号 × 持仓 → 建议。

此模块完全策略无关，只做查表映射，v1.0 到 v2.0 不需要修改。
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


def generate_advice(positions: list[dict],
                    signals: pd.DataFrame,
                    current_prices: dict[str, float],
                    risk_signals: dict[str, dict] | None = None) -> list[dict]:
    """交叉持仓与信号，返回操作建议列表。

    Args:
        positions: 持仓列表，每项含 id、code、cost、shares、entry_date
        signals: 信号 DataFrame，columns = [code, date, signal, signal_meta]
        current_prices: {code: close_price} 当前价格映射
        risk_signals: {code: {"signal": "SELL", "source": "stop_loss"}}，风控覆盖

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
    pos_map = {p["code"]: p for p in positions}

    results = []
    for _, row in signals.iterrows():
        code = row["code"]
        has_pos = code in pos_map

        # 风控覆盖优先
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
