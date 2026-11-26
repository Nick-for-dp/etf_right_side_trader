"""风控规则：按 ETF profile 止损。"""

from typing import Optional

from .base import BaseRiskRule, RiskResult


class ProfileStopLossRule(BaseRiskRule):
    """按 ETF 的 stop_loss_profile 计算止损线，浮亏触线 → 强制 SELL。

    profile 取自 settings.yaml 的 ETF 配置；ATR 类 profile 使用
    position["atr_pct"]（最近一日指标快照）。"none" 表示不止损。
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
        threshold = self.threshold(profile, position)

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
                threshold=threshold,
            )
        return None

    @classmethod
    def threshold(cls, profile: str, position: dict) -> float | None:
        """止损线（负的小数）；None 表示该持仓不止损。"""
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
