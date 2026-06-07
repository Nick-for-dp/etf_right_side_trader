"""Stop-loss risk rules."""

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


class ProfileStopLossRule(BaseRiskRule):
    """ETF profile based stop-loss rule.

    The profile name normally comes from ``settings.yaml`` ETF items. ATR
    profiles use ``atr_pct`` from the latest indicator snapshot.
    """

    _FIXED_THRESHOLDS = {
        "fixed_6": -0.06,
        "fixed_8": -0.08,
        "fixed_10": -0.10,
        "fixed_12": -0.12,
    }
    _ATR_PROFILES = {
        "atr_2_0": {"mult": 2.0, "min": -0.12, "max": -0.06},
        "atr_2_5": {"mult": 2.5, "min": -0.15, "max": -0.08},
        "atr_3_0": {"mult": 3.0, "min": -0.18, "max": -0.10},
    }

    def __init__(self, default_profile: str = "fixed_8"):
        self.default_profile = default_profile

    def check(self, position: dict, current_price: float) -> Optional[RiskResult]:
        cost = position["cost"]
        pnl_pct = (current_price - cost) / cost
        profile = position.get("stop_loss_profile") or self.default_profile
        threshold = self._threshold(profile, position)

        if threshold is None:
            return None
        if pnl_pct <= threshold:
            return RiskResult(
                triggered=True,
                signal="SELL",
                source="stop_loss",
                reason=(
                    f"{profile} 浮亏 {pnl_pct:.2%} ≤ 止损线 {threshold:.2%}，"
                    "强制卖出"
                ),
            )
        return None

    @classmethod
    def _threshold(cls, profile: str, position: dict) -> float | None:
        if profile == "none":
            return None
        if profile in cls._FIXED_THRESHOLDS:
            return cls._FIXED_THRESHOLDS[profile]
        atr_profile = cls._ATR_PROFILES.get(profile)
        if atr_profile is None:
            return cls._FIXED_THRESHOLDS["fixed_8"]
        atr_pct = position.get("atr_pct")
        if atr_pct is None:
            return None
        threshold = -float(atr_pct) * atr_profile["mult"]
        threshold = max(threshold, atr_profile["min"])
        threshold = min(threshold, atr_profile["max"])
        return threshold
