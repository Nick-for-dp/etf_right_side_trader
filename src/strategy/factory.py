"""策略工厂：根据 settings.yaml 创建策略实例。"""

from src.config import AppConfig
from .base import BaseStrategy


def create_strategy(config: AppConfig) -> BaseStrategy:
    """根据 config.strategy_type 创建并返回策略实例。

    Args:
        config: 应用配置对象，含 strategy_type 和 strategy_params 字段

    Returns:
        对应策略类型的实例，当前支持 "ma_cross"

    Example:
        >>> config = load_config()
        >>> strategy = create_strategy(config)
        >>> isinstance(strategy, BaseStrategy)
        True
    """
    stype = config.strategy_type
    params = config.strategy_params

    if stype == "ma_cross":
        from src.strategy.ma_cross import MaCrossStrategy
        return MaCrossStrategy(
            ma_short=params.get("ma_short", 20),
            ma_long=params.get("ma_long", 60),
        )

    if stype == "ma_cross_macd":
        from src.strategy.ma_cross_macd import MaCrossMacdStrategy
        return MaCrossMacdStrategy(
            ma_short=params.get("ma_short", 20),
            ma_long=params.get("ma_long", 60),
        )

    if stype == "multi_indicator_scoring":
        from src.strategy.multi_indicator_scoring import MultiIndicatorScoring
        return MultiIndicatorScoring(
            weights=params["weights"],
            thresholds=params["thresholds"],
        )

    raise ValueError(f"Unsupported strategy type: {stype}")
