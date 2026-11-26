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
    MAX_HOLDING = "max_holding"
    ADD_COOLDOWN = "add_cooldown"
    ADD_BUDGET = "add_budget"
    MARKET_REGIME = "market_regime"


class MarketState(StrEnum):
    """市场状态（三态）。

    RISK_OFF: 风险关闭，拦截建仓/加仓
    NORMAL:   正常交易
    UNKNOWN:  指数数据不足，不做拦截

    细分原因（过热回落 / 下跌趋势 / 恐慌 / 过热上涨 / 超卖反弹）
    保存在 market_regime.data.reason，不进入状态枚举。
    """

    RISK_OFF = "RISK_OFF"
    NORMAL = "NORMAL"
    UNKNOWN = "UNKNOWN"
