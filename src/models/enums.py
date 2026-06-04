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
    """市场热度状态。

    基础状态：COLD / NORMAL / HOT / UNKNOWN（基于涨跌幅+均线+RSI+成交额）
    细分状态（用于 advisor 精细门控）：
      - HOT_RISING:  过热但仍在上涨 → 降级为观望
      - HOT_FALLING: 过热且开始回落 → 严格拦截买入
      - BEAR_TREND:  过冷且趋势向下 → 拦截建仓加仓
      - PANIC:       恐慌低位（RSI 极低+放量）→ 拦截，提示人工观察
      - RECOVERY:    超卖后企稳反弹 → 允许小仓建仓
    """

    COLD = "COLD"
    NORMAL = "NORMAL"
    HOT = "HOT"
    HOT_RISING = "HOT_RISING"
    HOT_FALLING = "HOT_FALLING"
    BEAR_TREND = "BEAR_TREND"
    PANIC = "PANIC"
    RECOVERY = "RECOVERY"
    UNKNOWN = "UNKNOWN"
