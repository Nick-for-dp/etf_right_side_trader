"""风控规则抽象基类。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskResult:
    """风控检查结果。

    threshold: 触发时的止损线（仅止损规则填充），供回测归因复用。
    """

    triggered: bool
    signal: str          # BUY / SELL / HOLD
    source: str          # stop_loss / max_holding
    reason: str
    threshold: float | None = None


class BaseRiskRule(ABC):
    """风控规则抽象，每个规则实现 check 方法。"""

    @abstractmethod
    def check(self, position: dict, current_price: float) -> Optional[RiskResult]:
        """检查持仓是否需要风控干预。

        Args:
            position: {"id": int, "code": str, "cost": float, "shares": int,
                       "entry_date": str, "as_of_date": str,
                       "stop_loss_profile": str, "atr_pct": float}
            current_price: T-1 日收盘价

        Returns:
            RiskResult 若触发风控，None 若不需要干预
        """
        ...
