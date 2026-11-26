"""策略工厂：根据 settings.yaml 创建策略实例（仅多指标评分）。"""

from src.config import AppConfig
from .base import BaseStrategy


def create_strategy(config: AppConfig) -> BaseStrategy:
    """根据 config.strategy_type 创建并返回策略实例。

    Args:
        config: 应用配置对象，含 strategy_type 和 strategy_params 字段

    Returns:
        MultiIndicatorScoring 实例
    """
    from src.strategy.multi_indicator_scoring import MultiIndicatorScoring

    if config.strategy_type != "multi_indicator_scoring":
        raise ValueError(f"Unsupported strategy type: {config.strategy_type}")

    params = config.strategy_params
    code_volatility_groups = {
        item.symbol: item.volatility_group
        for item in config.etf_list
    }
    return MultiIndicatorScoring(
        weights=params["weights"],
        thresholds=params["thresholds"],
        volatility_signal_profiles=params.get("volatility_signal_profiles", {}),
        code_volatility_groups=code_volatility_groups,
    )
