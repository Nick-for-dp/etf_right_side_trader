"""风控控制器：遍历规则链，合并结果。"""

from src.config import AppConfig
from .base import BaseRiskRule, RiskResult
from .max_holding import MaxHoldingDaysRule
from .stop_loss import ProfileStopLossRule, StopLossRule
from .trailing_stop import TrailingStopRule


class RiskController:
    """管理风控规则链，按注册顺序执行，返回首个触发的结果。"""

    def __init__(self, config: AppConfig):
        """从配置加载风控规则链。"""
        self._rules: list[BaseRiskRule] = []
        self._load_from_config(config)

    def _load_from_config(self, config: AppConfig) -> None:
        """根据配置创建并注册风控规则。"""
        for rule_cfg in config.risk_rules:
            rtype = rule_cfg["type"]
            params = rule_cfg.get("params", {})
            if rtype == "stop_loss":
                self._rules.append(StopLossRule(
                    threshold=params.get("threshold", -0.08),
                ))
            elif rtype == "profile_stop_loss":
                self._rules.append(ProfileStopLossRule(
                    default_profile=params.get("default_profile", "fixed_8"),
                ))
            elif rtype == "max_holding_days":
                self._rules.append(MaxHoldingDaysRule(
                    max_days=params.get("days", 90),
                ))
            elif rtype == "trailing_stop":
                self._rules.append(TrailingStopRule(
                    profit_threshold=params.get("profit_threshold", 0.10),
                    drawdown_threshold=params.get("drawdown_threshold", 0.03),
                ))

    def register(self, rule: BaseRiskRule) -> None:
        """注册一条风控规则。"""
        self._rules.append(rule)

    def check_position(self, position: dict, current_price: float) -> RiskResult | None:
        """逐条检查持仓，返回首个触发的风控结果。

        Args:
            position: 持仓字典，含 id、code、cost、shares、entry_date
            current_price: T-1 日收盘价

        Returns:
            首个触发的 RiskResult，均未触发则返回 None
        """
        for rule in self._rules:
            result = rule.check(position, current_price)
            if result is not None:
                return result
        return None
