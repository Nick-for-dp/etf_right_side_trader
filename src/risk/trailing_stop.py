"""回撤止盈规则：浮盈达标后，从高点回撤超阈值触发卖出。

不做预测，只做跟随——涨上来后保护利润，防止坐过山车。
"""

from typing import Optional

from .base import BaseRiskRule, RiskResult


class TrailingStopRule(BaseRiskRule):
    """浮盈 ≥ profit_threshold 后激活，从持仓期间最高点回撤 ≥ drawdown_threshold 触发 SELL。

    params:
        profit_threshold:   激活门槛，默认 0.10（10%）
        drawdown_threshold: 回撤线，默认 0.03（3%）
    """

    def __init__(self, profit_threshold: float = 0.10, drawdown_threshold: float = 0.03):
        self.profit_threshold = profit_threshold
        self.drawdown_threshold = drawdown_threshold

    def check(self, position: dict, current_price: float) -> Optional[RiskResult]:
        """检查持仓是否需要回撤止盈。

        依赖 position dict 中的 peak_price 字段（由调用方在外部计算后传入）。

        Args:
            position:      含 id、code、cost、peak_price 等字段的持仓字典
            current_price: T-1 日收盘价

        Returns:
            RiskResult 若触发止盈，None 若无需干预
        """
        cost = position["cost"]
        peak_price = position.get("peak_price")

        # 无峰值数据（如新持仓首个交易日），不干预
        if peak_price is None:
            return None

        # 未激活：最高价未触及盈利门槛
        if (peak_price - cost) / cost < self.profit_threshold:
            return None

        # 已激活：检查回撤
        drawdown = (peak_price - current_price) / peak_price
        if drawdown >= self.drawdown_threshold:
            return RiskResult(
                triggered=True,
                signal="SELL",
                source="trailing_stop",
                reason=(
                    f"浮盈达{(peak_price - cost) / cost:.1%}后"
                    f"回撤{drawdown:.1%} ≥ {self.drawdown_threshold:.1%}，止盈卖出"
                ),
            )
        return None
