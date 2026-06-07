"""Maximum holding-period risk rule."""

from datetime import date
from typing import Optional

from .base import BaseRiskRule, RiskResult


class MaxHoldingDaysRule(BaseRiskRule):
    """Force exit when a position reaches the configured natural-day holding cap."""

    def __init__(self, max_days: int):
        self.max_days = max_days

    def check(self, position: dict, current_price: float) -> Optional[RiskResult]:
        entry_date = _parse_date(position.get("entry_date"))
        as_of_date = _parse_date(position.get("as_of_date"))
        if entry_date is None or as_of_date is None:
            return None
        holding_days = (as_of_date - entry_date).days
        if holding_days >= self.max_days:
            return RiskResult(
                triggered=True,
                signal="SELL",
                source="max_holding",
                reason=f"持有 {holding_days} 天 ≥ {self.max_days} 天上限，按交易周期退出",
            )
        return None


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
