"""固定止损规则（MVP）。"""

from typing import Optional

from .base import BaseRiskRule, RiskResult


class StopLossRule(BaseRiskRule):
    """持仓浮亏超过阈值 → 强制 SELL。

    params:
        threshold: 止损线，默认 -0.08（-8%）
    """

    def __init__(self, threshold: float = -0.08):
        """初始化止损线阈值。"""
        self.threshold = threshold

    def check(self, position: dict, current_price: float) -> Optional[RiskResult]:
        """计算持仓盈亏，触发时返回 SELL 风控结果。

        Args:
            position: 持仓字典，含 cost、shares 等字段
            current_price: T-1 日收盘价

        Returns:
            RiskResult 若浮亏达到阈值，None 若无需干预
        """
        cost = position["cost"]
        pnl_pct = (current_price - cost) / cost

        if pnl_pct <= self.threshold:
            return RiskResult(
                triggered=True,
                signal="SELL",
                source="stop_loss",
                reason=f"浮亏 {pnl_pct:.2%} ≤ 止损线 {self.threshold:.2%}，强制卖出",
            )
        return None
