"""业务枚举定义。"""

from enum import StrEnum


class SignalType(StrEnum):
    """策略信号。"""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradeAction(StrEnum):
    """用户真实交易动作。"""

    BUY = "BUY"
    ADD = "ADD"
    REDUCE = "REDUCE"
    SELL = "SELL"


class AdviceAction(StrEnum):
    """中文操作建议。"""

    OPEN = "建仓"
    ADD = "加仓"
    WATCH = "观望"
    NO_OP = "不操作"
    HOLD = "继续持有"
    SELL = "卖出"


class SignalSource(StrEnum):
    """建议来源。"""

    TREND = "trend"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    ADD_COOLDOWN = "add_cooldown"
    MARKET_REGIME = "market_regime"


class MarketState(StrEnum):
    """市场热度状态。"""

    COLD = "COLD"
    NORMAL = "NORMAL"
    HOT = "HOT"
    UNKNOWN = "UNKNOWN"
