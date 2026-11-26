"""Ablation experiment configuration.

The first ablation layer is intentionally limited to backtest-time switches.
It does not change persisted signals or production strategy parameters.
"""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class TradingCycleProfile:
    """Business-facing trading-cycle metadata for experiments."""

    name: str
    label: str
    ma_short: int
    ma_long: int
    max_holding_days: int | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AddRuleConfig:
    """Backtest-only add-position execution rule."""

    name: str
    label: str
    disabled: bool = False
    require_profit: bool = False
    min_score: float | None = None
    max_add_to_current_ratio: float | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BudgetAddStepConfig:
    """One reserve-budget add step."""

    reserve_ratio: float
    require_profit: bool = True
    min_score: float | None = None


@dataclass(frozen=True)
class EntryAddBudgetRuleConfig:
    """Backtest-only entry/add budget allocation rule."""

    name: str
    label: str
    entry_ratio: float
    add_steps: tuple[BudgetAddStepConfig, ...] = ()
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StopLossRuleConfig:
    """Backtest-only stop-loss rule configuration."""

    name: str
    label: str
    kind: str
    threshold: float | None = None
    atr_mult: float | None = None
    min_threshold: float | None = None
    max_threshold: float | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReentryRuleConfig:
    """Backtest-only filter for entries after a stop-loss exit."""

    name: str
    label: str
    cooldown_days: int = 0
    cooldown_trading_days: int = 0
    min_score: float | None = None
    require_close_above_ma20: bool = False
    require_ma20_above_ma60: bool = False
    stop_price_atr_buffer: float | None = None
    min_adx: float | None = None
    require_macd_positive: bool = False
    volatility_groups: tuple[str, ...] = ()
    regime_groups: tuple[str, ...] = ()
    require_price_above_stop_price: bool = False
    skip_one_buy_after_stop: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RelativeStrengthRuleConfig:
    """Backtest-only cross-sectional relative-strength rule."""

    name: str
    label: str
    score_kind: str = "return"  # return / excess
    mode: str = "rank"          # rank / filter
    windows: tuple[int, ...] = (20, 60, 120)
    weights: tuple[float, ...] = (0.5, 0.3, 0.2)
    top_quantile: float | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VolatilityStrategyRuleConfig:
    """Backtest-only execution rule scoped by ETF volatility group."""

    name: str
    label: str
    volatility_groups: tuple[str, ...]
    regime_groups: tuple[str, ...] = ()
    min_entry_score: float | None = None
    min_add_scores: tuple[float | None, ...] = ()
    disable_add: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentalSignalProfileConfig:
    """Backtest-only bottom-layer signal profile."""

    name: str
    label: str
    kind: str
    volatility_groups: tuple[str, ...]
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentalRiskProfileConfig:
    """Backtest-only risk profile for candidate strategy validation."""

    name: str
    label: str
    kind: str
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HighVolFrequencyControlRuleConfig:
    """Backtest-only frequency control rule for high-volatility ETF experiments."""

    name: str
    label: str
    buy_confirm_days: int = 1
    sell_confirm_days: int = 1
    min_holding_trading_days: int = 0
    add_interval_trading_days: int = 0
    max_high_vol_positions: int | None = None
    high_vol_stop_loss_threshold: float | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HighVolQualityControlRuleConfig:
    """Backtest-only trade-quality control rule for high-volatility ETF experiments."""

    name: str
    label: str
    min_entry_score: float | None = None
    min_entry_macd: float | None = None
    min_entry_rsi: float | None = None
    daily_entry_limit: int | None = None
    medium_entry_score: float | None = None
    medium_budget_multiplier: float = 1.0
    strong_entry_score: float | None = None
    strong_budget_multiplier: float = 1.0
    weak_budget_multiplier: float | None = None
    min_add_score: float | None = None
    min_add_macd: float | None = None
    high_vol_stop_loss_threshold: float | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioRiskRuleConfig:
    """Backtest-only portfolio-level exposure and concentration rule."""

    name: str
    label: str
    max_single_position_ratio: float | None = None
    max_total_exposure: float | None = None
    max_high_vol_exposure: float | None = None
    max_positions: int | None = None
    max_high_vol_positions: int | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)



ADD_RULE_BASELINE = AddRuleConfig(
    name="baseline",
    label="当前规则",
    description="持仓 BUY 通过门控和冷却后即可加仓，仍受单 ETF 仓位上限约束。",
)

ADD_RULE_DISABLED = AddRuleConfig(
    name="disabled",
    label="禁止加仓",
    disabled=True,
    description="建仓后不再执行加仓。",
)

ADD_RULE_PROFIT_ONLY = AddRuleConfig(
    name="profit_only",
    label="盈利才加仓",
    require_profit=True,
    max_add_to_current_ratio=1.0,
    description="只有当前价格高于持仓均价时才允许加仓。",
)

ADD_RULE_PROFIT_SCORE60 = AddRuleConfig(
    name="profit_score60",
    label="盈利且强信号",
    require_profit=True,
    min_score=60.0,
    max_add_to_current_ratio=1.0,
    description="盈利且技术评分 score >= 60 时才允许加仓。",
)

ADD_RULE_PYRAMID_50 = AddRuleConfig(
    name="pyramid_50",
    label="金字塔50%",
    require_profit=True,
    max_add_to_current_ratio=0.5,
    description="盈利时才加仓，且本次加仓份额不超过当前持仓份额的 50%。",
)

ADD_RULE_PYRAMID_33 = AddRuleConfig(
    name="pyramid_33",
    label="金字塔33%",
    require_profit=True,
    max_add_to_current_ratio=1 / 3,
    description="盈利时才加仓，且本次加仓份额不超过当前持仓份额的 33%。",
)

BUDGET_RULE_100_NO_ADD = EntryAddBudgetRuleConfig(
    name="budget_100_no_add",
    label="100%建仓",
    entry_ratio=1.0,
    add_steps=(),
    description="100% 目标仓位一次性建仓，不执行加仓。",
)

BUDGET_RULE_80_20_PROFIT = EntryAddBudgetRuleConfig(
    name="budget_80_20_profit",
    label="80/20盈利",
    entry_ratio=0.8,
    add_steps=(BudgetAddStepConfig(reserve_ratio=0.2, require_profit=True),),
    description="80% 目标仓位建仓，20% 储备资金在浮盈时加仓。",
)

BUDGET_RULE_80_20_SCORE60 = EntryAddBudgetRuleConfig(
    name="budget_80_20_score60",
    label="80/20强信号",
    entry_ratio=0.8,
    add_steps=(BudgetAddStepConfig(reserve_ratio=0.2, require_profit=True, min_score=60.0),),
    description="80% 目标仓位建仓，20% 储备资金在浮盈且 score >= 60 时加仓。",
)

BUDGET_RULE_80_10_10_LADDER = EntryAddBudgetRuleConfig(
    name="budget_80_10_10_ladder",
    label="80/10/10阶梯",
    entry_ratio=0.8,
    add_steps=(
        BudgetAddStepConfig(reserve_ratio=0.1, require_profit=True, min_score=60.0),
        BudgetAddStepConfig(reserve_ratio=0.1, require_profit=True, min_score=70.0),
    ),
    description="80% 建仓，两次 10% 储备；加仓阈值分别为 score >= 60 / 70。",
)

BUDGET_RULE_70_30_PROFIT = EntryAddBudgetRuleConfig(
    name="budget_70_30_profit",
    label="70/30盈利",
    entry_ratio=0.7,
    add_steps=(BudgetAddStepConfig(reserve_ratio=0.3, require_profit=True),),
    description="70% 目标仓位建仓，30% 储备资金在浮盈时加仓。",
)

BUDGET_RULE_70_15_15_LADDER = EntryAddBudgetRuleConfig(
    name="budget_70_15_15_ladder",
    label="70/15/15阶梯",
    entry_ratio=0.7,
    add_steps=(
        BudgetAddStepConfig(reserve_ratio=0.15, require_profit=True, min_score=60.0),
        BudgetAddStepConfig(reserve_ratio=0.15, require_profit=True, min_score=70.0),
    ),
    description="70% 建仓，两次 15% 储备；加仓阈值分别为 score >= 60 / 70。",
)

STOP_LOSS_NONE = StopLossRuleConfig(
    name="stop_none",
    label="不止损",
    kind="none",
    description="不启用固定止损，仅保留 90 日持有期退出。",
)

STOP_LOSS_FIXED_6 = StopLossRuleConfig(
    name="stop_fixed_6",
    label="固定-6%",
    kind="fixed",
    threshold=-0.06,
)

STOP_LOSS_FIXED_8 = StopLossRuleConfig(
    name="stop_fixed_8",
    label="固定-8%",
    kind="fixed",
    threshold=-0.08,
)

STOP_LOSS_FIXED_10 = StopLossRuleConfig(
    name="stop_fixed_10",
    label="固定-10%",
    kind="fixed",
    threshold=-0.10,
)

STOP_LOSS_FIXED_12 = StopLossRuleConfig(
    name="stop_fixed_12",
    label="固定-12%",
    kind="fixed",
    threshold=-0.12,
)

STOP_LOSS_ATR_2_0 = StopLossRuleConfig(
    name="stop_atr_2_0",
    label="ATRx2.0",
    kind="atr",
    atr_mult=2.0,
    min_threshold=-0.12,
    max_threshold=-0.06,
    description="止损线 = -2.0 * atr_pct，并限制在 -6% 到 -12%。",
)

STOP_LOSS_ATR_2_5 = StopLossRuleConfig(
    name="stop_atr_2_5",
    label="ATRx2.5",
    kind="atr",
    atr_mult=2.5,
    min_threshold=-0.15,
    max_threshold=-0.08,
    description="止损线 = -2.5 * atr_pct，并限制在 -8% 到 -15%。",
)

STOP_LOSS_ATR_3_0 = StopLossRuleConfig(
    name="stop_atr_3_0",
    label="ATRx3.0",
    kind="atr",
    atr_mult=3.0,
    min_threshold=-0.18,
    max_threshold=-0.10,
    description="止损线 = -3.0 * atr_pct，并限制在 -10% 到 -18%。",
)

STOP_LOSS_PROFILE_RULES = {
    "none": STOP_LOSS_NONE,
    "fixed_6": STOP_LOSS_FIXED_6,
    "fixed_8": STOP_LOSS_FIXED_8,
    "fixed_10": STOP_LOSS_FIXED_10,
    "fixed_12": STOP_LOSS_FIXED_12,
    "atr_2_0": STOP_LOSS_ATR_2_0,
    "atr_2_5": STOP_LOSS_ATR_2_5,
    "atr_3_0": STOP_LOSS_ATR_3_0,
}


def stop_loss_rule_from_profile(profile: str | None) -> StopLossRuleConfig:
    """Return the stop-loss rule represented by a settings.yaml profile."""

    return STOP_LOSS_PROFILE_RULES.get(profile or "fixed_8", STOP_LOSS_FIXED_8)


REENTRY_COOLDOWN_10 = ReentryRuleConfig(
    name="reentry_cooldown_10",
    label="冷静10日",
    cooldown_days=10,
    description="止损后至少等待 10 个自然日才允许再次建仓。",
)

REENTRY_COOLDOWN_20 = ReentryRuleConfig(
    name="reentry_cooldown_20",
    label="冷静20日",
    cooldown_days=20,
    description="止损后至少等待 20 个自然日才允许再次建仓。",
)

REENTRY_SCORE_60 = ReentryRuleConfig(
    name="reentry_score_60",
    label="score>=60",
    min_score=60.0,
    description="止损后再次建仓要求原 BUY 信号 score >= 60。",
)

REENTRY_SCORE_65 = ReentryRuleConfig(
    name="reentry_score_65",
    label="score>=65",
    min_score=65.0,
    description="止损后再次建仓要求原 BUY 信号 score >= 65。",
)

REENTRY_PRICE_RECLAIM = ReentryRuleConfig(
    name="reentry_price_reclaim",
    label="价格修复",
    require_close_above_ma20=True,
    stop_price_atr_buffer=0.5,
    description="止损后再次建仓要求收盘价站上 MA20，且高于止损价 0.5ATR。",
)

REENTRY_TREND_REPAIR = ReentryRuleConfig(
    name="reentry_trend_repair",
    label="趋势修复",
    require_close_above_ma20=True,
    require_ma20_above_ma60=True,
    min_adx=20.0,
    require_macd_positive=True,
    description="止损后再次建仓要求 MA20/MA60 趋势修复、ADX>=20 且 MACD 动能为正。",
)

REENTRY_COMPOSITE = ReentryRuleConfig(
    name="reentry_composite",
    label="复合修复",
    cooldown_days=10,
    min_score=60.0,
    require_close_above_ma20=True,
    stop_price_atr_buffer=0.5,
    min_adx=20.0,
    require_macd_positive=True,
    description="冷静期 + 强 score + 价格修复 + 趋势动能修复。",
)

REENTRY_COOLDOWN_3T = ReentryRuleConfig(
    name="reentry_cooldown_3t",
    label="3T冷却",
    cooldown_trading_days=3,
    description="止损后至少等待 3 个交易日后才允许再次建仓。",
)

REENTRY_PRICE_ABOVE_STOP = ReentryRuleConfig(
    name="reentry_price_above_stop",
    label="止损价约束",
    require_price_above_stop_price=True,
    description="止损后重新入场价必须高于止损卖出价，避免低位卖出后高位接回。",
)

REENTRY_HIGH_VOL_PRICE_ABOVE_STOP = ReentryRuleConfig(
    name="reentry_high_vol_price_above_stop",
    label="高波止损价",
    require_price_above_stop_price=True,
    volatility_groups=("high_vol",),
    description="仅高波动 ETF 止损后重新入场价必须高于止损卖出价。",
)

REENTRY_A_SHARE_HIGH_VOL_PRICE_ABOVE_STOP = ReentryRuleConfig(
    name="reentry_a_high_vol_price_above_stop",
    label="A高波止损价",
    require_price_above_stop_price=True,
    volatility_groups=("high_vol",),
    regime_groups=("A股",),
    description="仅 A股高波动 ETF 止损后重新入场价必须高于止损卖出价。",
)

REENTRY_LOW_VOL_PRICE_ABOVE_STOP = ReentryRuleConfig(
    name="reentry_low_vol_price_above_stop",
    label="低波止损价",
    require_price_above_stop_price=True,
    volatility_groups=("low_vol",),
    description="仅低波动 ETF 止损后重新入场价必须高于止损卖出价，用作反证组。",
)

REENTRY_SKIP_FIRST_BUY = ReentryRuleConfig(
    name="reentry_skip_first_buy",
    label="跳过首BUY",
    skip_one_buy_after_stop=True,
    description="止损后跳过第一个BUY信号，等第二个新BUY才重新入场。",
)

REENTRY_HIGH_VOL_COOLDOWN_10T = ReentryRuleConfig(
    name="reentry_high_vol_cooldown_10t",
    label="高波10T",
    cooldown_trading_days=10,
    volatility_groups=("high_vol",),
    description="仅高波动 ETF 止损后等待 10 个交易日，期满后按普通建仓处理。",
)

REENTRY_HIGH_VOL_COOLDOWN_15T = ReentryRuleConfig(
    name="reentry_high_vol_cooldown_15t",
    label="高波15T",
    cooldown_trading_days=15,
    volatility_groups=("high_vol",),
    description="仅高波动 ETF 止损后等待 15 个交易日，期满后按普通建仓处理。",
)

REENTRY_HIGH_VOL_COOLDOWN_20T = ReentryRuleConfig(
    name="reentry_high_vol_cooldown_20t",
    label="高波20T",
    cooldown_trading_days=20,
    volatility_groups=("high_vol",),
    description="仅高波动 ETF 止损后等待 20 个交易日，期满后按普通建仓处理。",
)

REENTRY_HIGH_VOL_COOLDOWN_30T = ReentryRuleConfig(
    name="reentry_high_vol_cooldown_30t",
    label="高波30T",
    cooldown_trading_days=30,
    volatility_groups=("high_vol",),
    description="仅高波动 ETF 止损后等待 30 个交易日，期满后按普通建仓处理。",
)

REENTRY_A_SHARE_HIGH_VOL_COOLDOWN_20T = ReentryRuleConfig(
    name="reentry_a_high_vol_cooldown_20t",
    label="A高波20T",
    cooldown_trading_days=20,
    volatility_groups=("high_vol",),
    regime_groups=("A股",),
    description="仅 A股高波动 ETF 止损后等待 20 个交易日。",
)

REENTRY_LOW_VOL_COOLDOWN_20T = ReentryRuleConfig(
    name="reentry_low_vol_cooldown_20t",
    label="低波20T",
    cooldown_trading_days=20,
    volatility_groups=("low_vol",),
    description="仅低波动 ETF 止损后等待 20 个交易日，用作反证组。",
)


RS_20_60_120_RANK = RelativeStrengthRuleConfig(
    name="rs_20_60_120_rank",
    label="RS收益排序",
    score_kind="return",
    mode="rank",
    windows=(20, 60, 120),
    weights=(0.5, 0.3, 0.2),
    description="按 20/60/120 日收益综合分排序买入类候选。",
)

RS_EXCESS_BENCHMARK_RANK = RelativeStrengthRuleConfig(
    name="rs_excess_benchmark_rank",
    label="RS超额排序",
    score_kind="excess",
    mode="rank",
    windows=(20, 60, 120),
    weights=(0.5, 0.3, 0.2),
    description="按相对所属市场基准的 20/60/120 日超额收益排序买入类候选。",
)

RS_TOP_40_FILTER = RelativeStrengthRuleConfig(
    name="rs_top_40_filter",
    label="RS前40%",
    score_kind="return",
    mode="filter",
    windows=(20, 60, 120),
    weights=(0.5, 0.3, 0.2),
    top_quantile=0.4,
    description="只允许 20/60/120 日综合强弱排名前 40% 的 BUY 进入建仓/加仓。",
)

VOL_HIGH_STRICT = VolatilityStrategyRuleConfig(
    name="vol_high_strict",
    label="高波严格",
    volatility_groups=("high_vol",),
    min_entry_score=60.0,
    min_add_scores=(70.0, 75.0),
    description="高波动 ETF 建仓要求 score >= 60，加仓两阶阈值提高到 70/75。",
)

VOL_LOW_LENIENT_ADD = VolatilityStrategyRuleConfig(
    name="vol_low_lenient_add",
    label="低波宽加",
    volatility_groups=("low_vol",),
    min_add_scores=(55.0, 60.0),
    description="低波动 ETF 保持原建仓信号，仅把两阶加仓阈值放宽到 55/60。",
)

SIGNAL_PROFILE_HIGH_VOL_BALANCED = ExperimentalSignalProfileConfig(
    name="signal_high_vol_balanced",
    label="高波新信号",
    kind="high_vol_balanced",
    volatility_groups=("high_vol",),
    description=(
        "高波动底层信号：趋势门槛 + 动能/RSI/布林位置/成交量/ATR 均衡评分，"
        "趋势权重 30%，避免趋势单因子主导。"
    ),
)

SIGNAL_PROFILE_LOW_VOL_STABLE = ExperimentalSignalProfileConfig(
    name="signal_low_vol_stable",
    label="低波新信号",
    kind="low_vol_stable",
    volatility_groups=("low_vol",),
    description=(
        "低波动底层信号：趋势稳定 + RSI/布林修复 + 温和 MACD，"
        "不强制 ADX 高趋势。"
    ),
)

RISK_PROFILE_HIGH_VOL_TREND = ExperimentalRiskProfileConfig(
    name="risk_high_vol_trend",
    label="高波趋势风控",
    kind="high_vol_trend",
    description="高波动风控：ATR 初始止损 + 盈利后 ATR 移动止损 + MA20/MACD 趋势转弱退出。",
)

RISK_PROFILE_LOW_VOL_STRUCTURE = ExperimentalRiskProfileConfig(
    name="risk_low_vol_structure",
    label="低波结构风控",
    kind="low_vol_structure",
    description="低波动风控：结构破坏退出 + -12% 灾难止损 + 180 日最大持有。",
)

HIGH_VOL_STOP12 = HighVolFrequencyControlRuleConfig(
    name="high_vol_stop12",
    label="高波止损12%",
    high_vol_stop_loss_threshold=-0.12,
    description="只调整 high_vol 固定止损阈值为 -12%，不增加交易频率过滤。",
)

HIGH_VOL_BUY_CONFIRM_2 = HighVolFrequencyControlRuleConfig(
    name="high_vol_buy_confirm_2",
    label="BUY确认2日",
    buy_confirm_days=2,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol BUY 连续 2 个交易日出现才允许建仓。",
)

HIGH_VOL_BUY_CONFIRM_3 = HighVolFrequencyControlRuleConfig(
    name="high_vol_buy_confirm_3",
    label="BUY确认3日",
    buy_confirm_days=3,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol BUY 连续 3 个交易日出现才允许建仓。",
)

HIGH_VOL_ADD_INTERVAL_10 = HighVolFrequencyControlRuleConfig(
    name="high_vol_add_interval_10",
    label="加仓间隔10T",
    add_interval_trading_days=10,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol 同一 ETF 两次加仓至少间隔 10 个交易日。",
)

HIGH_VOL_SELL_CONFIRM_2 = HighVolFrequencyControlRuleConfig(
    name="high_vol_sell_confirm_2",
    label="SELL确认2日",
    sell_confirm_days=2,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol 普通 SELL 连续 2 个交易日出现才执行卖出，风控退出不延迟。",
)

HIGH_VOL_SELL_CONFIRM_3 = HighVolFrequencyControlRuleConfig(
    name="high_vol_sell_confirm_3",
    label="SELL确认3日",
    sell_confirm_days=3,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol 普通 SELL 连续 3 个交易日出现才执行卖出，风控退出不延迟。",
)

HIGH_VOL_MIN_HOLD_5 = HighVolFrequencyControlRuleConfig(
    name="high_vol_min_hold_5",
    label="最小持有5T",
    min_holding_trading_days=5,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol 建仓后 5 个交易日内忽略普通 SELL，风控退出不延迟。",
)

HIGH_VOL_MIN_HOLD_10 = HighVolFrequencyControlRuleConfig(
    name="high_vol_min_hold_10",
    label="最小持有10T",
    min_holding_trading_days=10,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol 建仓后 10 个交易日内忽略普通 SELL，风控退出不延迟。",
)

HIGH_VOL_MAX_POS_6 = HighVolFrequencyControlRuleConfig(
    name="high_vol_max_pos_6",
    label="高波最多6只",
    max_high_vol_positions=6,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol 同时持仓最多 6 只，超过后不再新建仓。",
)

HIGH_VOL_BUY2_ADD10 = HighVolFrequencyControlRuleConfig(
    name="high_vol_buy2_add10",
    label="BUY2+加仓10T",
    buy_confirm_days=2,
    add_interval_trading_days=10,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol BUY 连续 2 日确认，并限制同 ETF 加仓间隔 10 个交易日。",
)

HIGH_VOL_BUY2_SELL2 = HighVolFrequencyControlRuleConfig(
    name="high_vol_buy2_sell2",
    label="BUY2+SELL2",
    buy_confirm_days=2,
    sell_confirm_days=2,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol BUY 和普通 SELL 都要求连续 2 日确认。",
)

HIGH_VOL_BUY2_HOLD5_ADD10 = HighVolFrequencyControlRuleConfig(
    name="high_vol_buy2_hold5_add10",
    label="BUY2+持5+加10",
    buy_confirm_days=2,
    min_holding_trading_days=5,
    add_interval_trading_days=10,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol BUY 2 日确认、最小持有 5T、加仓间隔 10T。",
)

HIGH_VOL_BUY2_MAX6 = HighVolFrequencyControlRuleConfig(
    name="high_vol_buy2_max6",
    label="BUY2+最多6",
    buy_confirm_days=2,
    max_high_vol_positions=6,
    high_vol_stop_loss_threshold=-0.12,
    description="high_vol BUY 2 日确认，并限制高波动同时持仓最多 6 只。",
)


HIGH_VOL_QUALITY_SCORE55 = HighVolQualityControlRuleConfig(
    name="high_vol_quality_score55",
    label="BUY分>=55",
    min_entry_score=55.0,
    description="high_vol 新建仓要求实验信号 score >= 55，过滤低质量 BUY。",
)

HIGH_VOL_QUALITY_MOMENTUM = HighVolQualityControlRuleConfig(
    name="high_vol_quality_momentum",
    label="动能确认",
    min_entry_score=50.0,
    min_entry_macd=0.0,
    min_entry_rsi=-0.1,
    description="high_vol 新建仓要求 score >= 50、MACD 分量为正且 RSI 分量不明显拖累。",
)

HIGH_VOL_QUALITY_DAILY_TOP2 = HighVolQualityControlRuleConfig(
    name="high_vol_quality_daily_top2",
    label="每日前2",
    daily_entry_limit=2,
    description="同一交易日 high_vol 建仓候选按 score 排序，只允许前 2 个进入执行。",
)

HIGH_VOL_QUALITY_BUDGET_TIER = HighVolQualityControlRuleConfig(
    name="high_vol_quality_budget_tier",
    label="质量分层仓位",
    medium_entry_score=55.0,
    medium_budget_multiplier=0.80,
    strong_entry_score=65.0,
    strong_budget_multiplier=1.0,
    weak_budget_multiplier=0.60,
    description="high_vol 目标仓位按信号质量分层：score>=65 满额，55-65 为 80%，低于55为 60%。",
)

HIGH_VOL_QUALITY_TIER_MILD = HighVolQualityControlRuleConfig(
    name="high_vol_quality_tier_mild",
    label="温和分层",
    medium_entry_score=55.0,
    medium_budget_multiplier=0.90,
    strong_entry_score=65.0,
    strong_budget_multiplier=1.0,
    weak_budget_multiplier=0.75,
    description="high_vol 目标仓位按信号质量温和分层：score>=65 满额，55-65 为 90%，低于55为 75%。",
)

HIGH_VOL_QUALITY_TIER_STRICT = HighVolQualityControlRuleConfig(
    name="high_vol_quality_tier_strict",
    label="严格阈值分层",
    medium_entry_score=60.0,
    medium_budget_multiplier=0.80,
    strong_entry_score=70.0,
    strong_budget_multiplier=1.0,
    weak_budget_multiplier=0.60,
    description="high_vol 目标仓位按更高阈值分层：score>=70 满额，60-70 为 80%，低于60为 60%。",
)

HIGH_VOL_QUALITY_TIER_DEFENSIVE = HighVolQualityControlRuleConfig(
    name="high_vol_quality_tier_defensive",
    label="强控仓位分层",
    medium_entry_score=55.0,
    medium_budget_multiplier=0.75,
    strong_entry_score=65.0,
    strong_budget_multiplier=0.90,
    weak_budget_multiplier=0.50,
    description="high_vol 目标仓位按信号质量强控仓位：score>=65 为 90%，55-65 为 75%，低于55为 50%。",
)

HIGH_VOL_QUALITY_ADD_STRICT = HighVolQualityControlRuleConfig(
    name="high_vol_quality_add_strict",
    label="强加仓",
    min_add_score=68.0,
    min_add_macd=0.0,
    description="high_vol 加仓除原 70/15/15 条件外，要求 score >= 68 且 MACD 分量为正。",
)

HIGH_VOL_QUALITY_SCORE_TOP2 = HighVolQualityControlRuleConfig(
    name="high_vol_quality_score55_top2",
    label="分数+每日前2",
    min_entry_score=55.0,
    daily_entry_limit=2,
    description="过滤 score<55 的 high_vol 建仓，并限制同日 high_vol 建仓候选最多 2 个。",
)

HIGH_VOL_QUALITY_SCORE_BUDGET = HighVolQualityControlRuleConfig(
    name="high_vol_quality_score55_budget",
    label="分数+分层仓位",
    min_entry_score=55.0,
    medium_entry_score=60.0,
    medium_budget_multiplier=0.85,
    strong_entry_score=68.0,
    strong_budget_multiplier=1.0,
    weak_budget_multiplier=0.70,
    description="过滤 score<55 的 high_vol 建仓，并按 score 下调中等质量信号目标仓位。",
)

HIGH_VOL_QUALITY_COMPOSITE = HighVolQualityControlRuleConfig(
    name="high_vol_quality_composite",
    label="质量组合",
    min_entry_score=55.0,
    min_entry_macd=0.0,
    daily_entry_limit=2,
    medium_entry_score=60.0,
    medium_budget_multiplier=0.85,
    strong_entry_score=68.0,
    strong_budget_multiplier=1.0,
    weak_budget_multiplier=0.70,
    min_add_score=68.0,
    min_add_macd=0.0,
    high_vol_stop_loss_threshold=-0.12,
    description=(
        "high_vol 建仓要求 score>=55 且 MACD 分量为正；同日最多 2 个建仓；"
        "中等质量信号降低目标仓位；加仓要求 score>=68 且 MACD 分量为正；"
        "高波止损阈值同步观察 -12%。"
    ),
)


PORTFOLIO_RISK_SINGLE_25 = PortfolioRiskRuleConfig(
    name="portfolio_single_25",
    label="单标25%",
    max_single_position_ratio=0.25,
    description="单 ETF 持仓市值不超过组合权益 25%，低于默认 30% 单标仓位上限。",
)

PORTFOLIO_RISK_TOTAL_85 = PortfolioRiskRuleConfig(
    name="portfolio_total_85",
    label="总仓85%",
    max_total_exposure=0.85,
    description="组合总持仓市值不超过组合权益 85%，保留至少约 15% 现金缓冲。",
)

PORTFOLIO_RISK_HIGH_VOL_25 = PortfolioRiskRuleConfig(
    name="portfolio_high_vol_25",
    label="高波25%",
    max_high_vol_exposure=0.25,
    description="high_vol 持仓市值不超过组合权益 25%，控制高波暴露峰值。",
)

PORTFOLIO_RISK_HIGH_VOL_20 = PortfolioRiskRuleConfig(
    name="portfolio_high_vol_20",
    label="高波20%",
    max_high_vol_exposure=0.20,
    description="high_vol 持仓市值不超过组合权益 20%，观察更强高波暴露约束的收益损耗。",
)

PORTFOLIO_RISK_MAX_POSITIONS_10 = PortfolioRiskRuleConfig(
    name="portfolio_max_positions_10",
    label="最多10只",
    max_positions=10,
    description="组合同时持仓最多 10 只 ETF，降低持仓分散度和尾部叠加。",
)

PORTFOLIO_RISK_HIGH_VOL_COUNT_4 = PortfolioRiskRuleConfig(
    name="portfolio_high_vol_count_4",
    label="高波最多4只",
    max_high_vol_positions=4,
    description="high_vol 同时持仓最多 4 只，控制高波主题拥挤。",
)

PORTFOLIO_RISK_MODERATE = PortfolioRiskRuleConfig(
    name="portfolio_risk_moderate",
    label="组合温和控险",
    max_single_position_ratio=0.25,
    max_total_exposure=0.90,
    max_high_vol_exposure=0.30,
    max_positions=12,
    max_high_vol_positions=5,
    description="温和组合风控：单标 25%、总仓 90%、高波 30%、最多 12 只且高波最多 5 只。",
)

PORTFOLIO_RISK_CONSERVATIVE = PortfolioRiskRuleConfig(
    name="portfolio_risk_conservative",
    label="组合强控险",
    max_single_position_ratio=0.25,
    max_total_exposure=0.85,
    max_high_vol_exposure=0.25,
    max_positions=10,
    max_high_vol_positions=4,
    description="强组合风控：单标 25%、总仓 85%、高波 25%、最多 10 只且高波最多 4 只。",
)

MONTHLY_QUARTER = TradingCycleProfile(
    name="monthly_quarter",
    label="月度-季度",
    ma_short=20,
    ma_long=60,
    max_holding_days=None,
    description="当前生产信号口径；MA20 约 1 个月，MA60 约 1 个季度。",
)

WEEKLY_SHORT = TradingCycleProfile(
    name="weekly_short",
    label="周度-月度",
    ma_short=10,
    ma_long=30,
    max_holding_days=None,
    description="预留实验组；第一版框架不重算此周期信号。",
)

QUARTERLY_MID = TradingCycleProfile(
    name="quarterly_mid",
    label="季度中线",
    ma_short=30,
    ma_long=90,
    max_holding_days=None,
    description="预留实验组；第一版框架不重算此周期信号。",
)

PREFERRED_QUARTER_HOLD_DAYS = 90

MONTHLY_QUARTER_90D = TradingCycleProfile(
    name="monthly_quarter_90d",
    label="月度-季度(90日)",
    ma_short=20,
    ma_long=60,
    max_holding_days=PREFERRED_QUARTER_HOLD_DAYS,
    description="当前生产信号口径；额外约束单笔持有不超过 90 个自然日。",
)


@dataclass(frozen=True)
class AblationExperimentConfig:
    """Backtest-time factor switch configuration."""

    name: str
    label: str
    use_premium_gate: bool = True
    use_market_gate: bool = True
    use_add_cooldown: bool = True
    use_stop_loss: bool = True
    use_position_limit: bool = True
    max_holding_days: int | None = None
    cycle_profile: TradingCycleProfile = field(default_factory=lambda: MONTHLY_QUARTER)
    add_rule: AddRuleConfig = field(default_factory=lambda: ADD_RULE_BASELINE)
    entry_add_budget_rule: EntryAddBudgetRuleConfig | None = None
    stop_loss_rule: StopLossRuleConfig | None = None
    use_config_stop_loss_profiles: bool = False
    reentry_rule: ReentryRuleConfig | None = None
    relative_strength_rule: RelativeStrengthRuleConfig | None = None
    volatility_strategy_rules: tuple[VolatilityStrategyRuleConfig, ...] = ()
    experimental_signal_profile: ExperimentalSignalProfileConfig | None = None
    experimental_risk_profile: ExperimentalRiskProfileConfig | None = None
    high_vol_frequency_rule: HighVolFrequencyControlRuleConfig | None = None
    high_vol_quality_rule: HighVolQualityControlRuleConfig | None = None
    portfolio_risk_rule: PortfolioRiskRuleConfig | None = None
    description: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["cycle_profile"] = self.cycle_profile.to_dict()
        data["add_rule"] = self.add_rule.to_dict()
        if self.entry_add_budget_rule is not None:
            data["entry_add_budget_rule"] = self.entry_add_budget_rule.to_dict()
        if self.stop_loss_rule is not None:
            data["stop_loss_rule"] = self.stop_loss_rule.to_dict()
        if self.reentry_rule is not None:
            data["reentry_rule"] = self.reentry_rule.to_dict()
        if self.relative_strength_rule is not None:
            data["relative_strength_rule"] = self.relative_strength_rule.to_dict()
        data["volatility_strategy_rules"] = [
            rule.to_dict()
            for rule in self.volatility_strategy_rules
        ]
        if self.experimental_signal_profile is not None:
            data["experimental_signal_profile"] = self.experimental_signal_profile.to_dict()
        if self.experimental_risk_profile is not None:
            data["experimental_risk_profile"] = self.experimental_risk_profile.to_dict()
        if self.high_vol_frequency_rule is not None:
            data["high_vol_frequency_rule"] = self.high_vol_frequency_rule.to_dict()
        if self.high_vol_quality_rule is not None:
            data["high_vol_quality_rule"] = self.high_vol_quality_rule.to_dict()
        if self.portfolio_risk_rule is not None:
            data["portfolio_risk_rule"] = self.portfolio_risk_rule.to_dict()
        return data


def legacy_portfolio_experiments() -> list[AblationExperimentConfig]:
    """Return configs matching the existing backtest-portfolio output."""

    return [
        AblationExperimentConfig(
            name="v2.3-tech-only",
            label="v2.3 技术信号",
            use_premium_gate=False,
            use_market_gate=False,
            use_add_cooldown=True,
            use_stop_loss=True,
            use_position_limit=True,
            description="兼容旧版输出：不启用买入门控，但保留原回测风控和冷却逻辑。",
        ),
        AblationExperimentConfig(
            name="v2.3-odds",
            label="v2.3 赔率门控",
            use_premium_gate=True,
            use_market_gate=False,
            use_add_cooldown=True,
            use_stop_loss=True,
            use_position_limit=True,
            description="兼容旧版输出：高溢价门控 + 原回测风控和冷却逻辑。",
        ),
        AblationExperimentConfig(
            name="v2.3-full-gate",
            label="v2.3 全门控",
            use_premium_gate=True,
            use_market_gate=True,
            use_add_cooldown=True,
            use_stop_loss=True,
            use_position_limit=True,
            description="当前生产门控口径：高溢价 + gate-lite 分市场门控。",
        ),
    ]


def default_ablation_experiments() -> list[AblationExperimentConfig]:
    """Return the first production-baseline ablation matrix."""

    return [
        AblationExperimentConfig(
            name="baseline_full_gate",
            label="Baseline 全门控",
            description="当前生产基线：高溢价、市场门控、加仓冷却、止损和单 ETF 仓位上限。",
        ),
        AblationExperimentConfig(
            name="signal_only",
            label="仅技术信号",
            use_premium_gate=False,
            use_market_gate=False,
            use_add_cooldown=False,
            use_stop_loss=False,
            use_position_limit=True,
            description="技术 BUY/SELL + 固定仓位执行；不启用买入门控、冷却或止损。",
        ),
        AblationExperimentConfig(
            name="premium_only_added",
            label="仅高溢价门控",
            use_premium_gate=True,
            use_market_gate=False,
            use_add_cooldown=False,
            use_stop_loss=False,
            use_position_limit=True,
            description="在技术信号基础上只增加高溢价拦截。",
        ),
        AblationExperimentConfig(
            name="market_only_added",
            label="仅市场门控",
            use_premium_gate=False,
            use_market_gate=True,
            use_add_cooldown=False,
            use_stop_loss=False,
            use_position_limit=True,
            description="在技术信号基础上只增加 gate-lite 市场门控。",
        ),
        AblationExperimentConfig(
            name="no_premium_gate",
            label="关闭高溢价",
            use_premium_gate=False,
            description="在生产基线中只关闭高溢价硬门控。",
        ),
        AblationExperimentConfig(
            name="no_market_gate",
            label="关闭市场门控",
            use_market_gate=False,
            description="在生产基线中只关闭 gate-lite 市场门控。",
        ),
        AblationExperimentConfig(
            name="no_add_cooldown",
            label="关闭加仓冷却",
            use_add_cooldown=False,
            description="在生产基线中只关闭加仓冷却。",
        ),
        AblationExperimentConfig(
            name="no_stop_loss",
            label="关闭止损",
            use_stop_loss=False,
            description="在生产基线中只关闭回测止损。",
        ),
    ]


def preferred_cycle_ablation_experiments() -> list[AblationExperimentConfig]:
    """Return ablation matrix constrained to the user's preferred cycle."""

    max_days = PREFERRED_QUARTER_HOLD_DAYS
    cycle = MONTHLY_QUARTER_90D
    return [
        AblationExperimentConfig(
            name="preferred_baseline_full_gate",
            label="周期Baseline 全门控",
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="当前生产基线 + 最长 90 自然日持有约束。",
        ),
        AblationExperimentConfig(
            name="preferred_signal_only",
            label="周期仅技术信号",
            use_premium_gate=False,
            use_market_gate=False,
            use_add_cooldown=False,
            use_stop_loss=False,
            use_position_limit=True,
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="90 日持有约束下的技术信号基准；不启用门控、冷却或止损。",
        ),
        AblationExperimentConfig(
            name="preferred_premium_only_added",
            label="周期仅高溢价",
            use_premium_gate=True,
            use_market_gate=False,
            use_add_cooldown=False,
            use_stop_loss=False,
            use_position_limit=True,
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="90 日持有约束下只增加高溢价拦截。",
        ),
        AblationExperimentConfig(
            name="preferred_market_only_added",
            label="周期仅市场门控",
            use_premium_gate=False,
            use_market_gate=True,
            use_add_cooldown=False,
            use_stop_loss=False,
            use_position_limit=True,
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="90 日持有约束下只增加 gate-lite 市场门控。",
        ),
        AblationExperimentConfig(
            name="preferred_no_premium_gate",
            label="周期关闭高溢价",
            use_premium_gate=False,
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="90 日持有约束下，在生产基线中只关闭高溢价硬门控。",
        ),
        AblationExperimentConfig(
            name="preferred_no_market_gate",
            label="周期关闭市场",
            use_market_gate=False,
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="90 日持有约束下，在生产基线中只关闭 gate-lite 市场门控。",
        ),
        AblationExperimentConfig(
            name="preferred_no_add_cooldown",
            label="周期关闭冷却",
            use_add_cooldown=False,
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="90 日持有约束下，在生产基线中只关闭加仓冷却。",
        ),
        AblationExperimentConfig(
            name="preferred_no_stop_loss",
            label="周期关闭止损",
            use_stop_loss=False,
            max_holding_days=max_days,
            cycle_profile=cycle,
            description="90 日持有约束下，在生产基线中只关闭回测止损。",
        ),
    ]


def add_rules_ablation_experiments() -> list[AblationExperimentConfig]:
    """Return add-position rule experiments under the preferred cycle."""

    max_days = PREFERRED_QUARTER_HOLD_DAYS
    cycle = MONTHLY_QUARTER_90D
    base_kwargs = {
        "max_holding_days": max_days,
        "cycle_profile": cycle,
    }
    return [
        AblationExperimentConfig(
            name="preferred_add_baseline",
            label="加仓Baseline",
            add_rule=ADD_RULE_BASELINE,
            description="90 日持有约束下的当前加仓规则。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="preferred_add_disabled",
            label="禁止加仓",
            add_rule=ADD_RULE_DISABLED,
            description="90 日持有约束下，建仓后不再执行加仓。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="preferred_add_profit_only",
            label="盈利才加仓",
            add_rule=ADD_RULE_PROFIT_ONLY,
            description="90 日持有约束下，只允许浮盈持仓加仓。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="preferred_add_profit_score60",
            label="盈利强信号",
            add_rule=ADD_RULE_PROFIT_SCORE60,
            description="90 日持有约束下，只允许浮盈且 score >= 60 的持仓加仓。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="preferred_add_pyramid_50",
            label="金字塔50%",
            add_rule=ADD_RULE_PYRAMID_50,
            description="90 日持有约束下，单次加仓不超过当前持仓份额 50%。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="preferred_add_pyramid_33",
            label="金字塔33%",
            add_rule=ADD_RULE_PYRAMID_33,
            description="90 日持有约束下，单次加仓不超过当前持仓份额 33%。",
            **base_kwargs,
        ),
    ]


def entry_add_budget_ablation_experiments() -> list[AblationExperimentConfig]:
    """Return entry/add budget allocation experiments under the preferred cycle."""

    max_days = PREFERRED_QUARTER_HOLD_DAYS
    cycle = MONTHLY_QUARTER_90D
    base_kwargs = {
        "max_holding_days": max_days,
        "cycle_profile": cycle,
    }
    return [
        AblationExperimentConfig(
            name="budget_100_no_add",
            label="100%建仓不加",
            entry_add_budget_rule=BUDGET_RULE_100_NO_ADD,
            description="100% 目标仓位一次性建仓，不执行加仓。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="budget_80_20_profit",
            label="80/20盈利",
            entry_add_budget_rule=BUDGET_RULE_80_20_PROFIT,
            description="80% 建仓，20% 储备；浮盈才加仓。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="budget_80_20_score60",
            label="80/20强信号",
            entry_add_budget_rule=BUDGET_RULE_80_20_SCORE60,
            description="80% 建仓，20% 储备；浮盈且 score >= 60 才加仓。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="budget_80_10_10_ladder",
            label="80/10/10阶梯",
            entry_add_budget_rule=BUDGET_RULE_80_10_10_LADDER,
            description="80% 建仓，两次 10% 储备；加仓阈值分别为 score >= 60 / 70。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="budget_70_30_profit",
            label="70/30盈利",
            entry_add_budget_rule=BUDGET_RULE_70_30_PROFIT,
            description="70% 建仓，30% 储备；浮盈才加仓。",
            **base_kwargs,
        ),
        AblationExperimentConfig(
            name="budget_70_15_15_ladder",
            label="70/15/15阶梯",
            entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
            description="70% 建仓，两次 15% 储备；加仓阈值分别为 score >= 60 / 70。",
            **base_kwargs,
        ),
    ]


def stop_loss_ablation_experiments() -> list[AblationExperimentConfig]:
    """Return stop-loss experiments using the selected 70/15/15 budget rule."""

    max_days = PREFERRED_QUARTER_HOLD_DAYS
    cycle = MONTHLY_QUARTER_90D
    base_kwargs = {
        "max_holding_days": max_days,
        "cycle_profile": cycle,
        "entry_add_budget_rule": BUDGET_RULE_70_15_15_LADDER,
    }
    rules = [
        STOP_LOSS_NONE,
        STOP_LOSS_FIXED_6,
        STOP_LOSS_FIXED_8,
        STOP_LOSS_FIXED_10,
        STOP_LOSS_FIXED_12,
        STOP_LOSS_ATR_2_0,
        STOP_LOSS_ATR_2_5,
        STOP_LOSS_ATR_3_0,
    ]
    return [
        AblationExperimentConfig(
            name=rule.name,
            label=rule.label,
            use_stop_loss=rule.kind != "none",
            stop_loss_rule=rule,
            description=f"70/15/15阶梯 + {rule.label} 止损。",
            **base_kwargs,
        )
        for rule in rules
    ]


def candidate_comparison_experiments() -> list[AblationExperimentConfig]:
    """Return production candidate comparison experiments."""

    max_days = PREFERRED_QUARTER_HOLD_DAYS
    cycle = MONTHLY_QUARTER_90D
    return [
        AblationExperimentConfig(
            name="baseline_v2_3_gate_lite_regime",
            label="baseline-v2.3",
            use_premium_gate=True,
            use_market_gate=True,
            use_add_cooldown=True,
            use_stop_loss=True,
            use_position_limit=True,
            stop_loss_rule=STOP_LOSS_FIXED_8,
            description="对照组：当前 baseline-v2.3 gate-lite + regime_group。",
        ),
        AblationExperimentConfig(
            name="candidate_70_15_15_fixed8",
            label="A 70/15/15",
            use_premium_gate=True,
            use_market_gate=True,
            use_add_cooldown=True,
            use_stop_loss=True,
            use_position_limit=True,
            max_holding_days=max_days,
            cycle_profile=cycle,
            entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
            stop_loss_rule=STOP_LOSS_FIXED_8,
            description="实验组A：baseline + 70/15/15阶梯建仓加仓 + 90日最大持有 + 固定-8%止损。",
        ),
        AblationExperimentConfig(
            name="candidate_70_15_15_segment_stop",
            label="B 分段止损",
            use_premium_gate=True,
            use_market_gate=True,
            use_add_cooldown=True,
            use_stop_loss=True,
            use_position_limit=True,
            max_holding_days=max_days,
            cycle_profile=cycle,
            entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
            stop_loss_rule=STOP_LOSS_FIXED_8,
            use_config_stop_loss_profiles=True,
            description=(
                "实验组B：baseline + 70/15/15阶梯建仓加仓 + 90日最大持有 "
                "+ settings.yaml 分市场/分波动止损 profile。"
            ),
        ),
    ]


def production_v2_4_experiment(
    *,
    name: str = "baseline_v2_4_segment_stop",
    label: str = "baseline-v2.4",
    max_holding_days: int | None = PREFERRED_QUARTER_HOLD_DAYS,
    stop_loss_rule: StopLossRuleConfig | None = STOP_LOSS_FIXED_8,
    use_config_stop_loss_profiles: bool = True,
    reentry_rule: ReentryRuleConfig | None = None,
    relative_strength_rule: RelativeStrengthRuleConfig | None = None,
    volatility_strategy_rules: tuple[VolatilityStrategyRuleConfig, ...] = (),
    experimental_signal_profile: ExperimentalSignalProfileConfig | None = None,
    experimental_risk_profile: ExperimentalRiskProfileConfig | None = None,
    high_vol_frequency_rule: HighVolFrequencyControlRuleConfig | None = None,
    high_vol_quality_rule: HighVolQualityControlRuleConfig | None = None,
    portfolio_risk_rule: PortfolioRiskRuleConfig | None = None,
    description: str | None = None,
) -> AblationExperimentConfig:
    """Return the confirmed v2.4 baseline: candidate B from the prior experiment."""

    cycle = MONTHLY_QUARTER_90D
    return AblationExperimentConfig(
        name=name,
        label=label,
        use_premium_gate=True,
        use_market_gate=True,
        use_add_cooldown=True,
        use_stop_loss=True,
        use_position_limit=True,
        max_holding_days=max_holding_days,
        cycle_profile=cycle,
        entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
        stop_loss_rule=stop_loss_rule,
        use_config_stop_loss_profiles=use_config_stop_loss_profiles,
        reentry_rule=reentry_rule,
        relative_strength_rule=relative_strength_rule,
        volatility_strategy_rules=volatility_strategy_rules,
        experimental_signal_profile=experimental_signal_profile,
        experimental_risk_profile=experimental_risk_profile,
        high_vol_frequency_rule=high_vol_frequency_rule,
        high_vol_quality_rule=high_vol_quality_rule,
        portfolio_risk_rule=portfolio_risk_rule,
        description=description or "新基线：70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有。",
    )


def no_risk_v2_4_control_experiment(
    *,
    name: str = "control_no_risk",
    label: str = "对照无风控",
    relative_strength_rule: RelativeStrengthRuleConfig | None = None,
    volatility_strategy_rules: tuple[VolatilityStrategyRuleConfig, ...] = (),
    description: str | None = None,
) -> AblationExperimentConfig:
    """Return baseline-v2.4 execution without stop-loss or max-holding exits."""

    return AblationExperimentConfig(
        name=name,
        label=label,
        use_premium_gate=True,
        use_market_gate=True,
        use_add_cooldown=True,
        use_stop_loss=False,
        use_position_limit=True,
        max_holding_days=None,
        cycle_profile=MONTHLY_QUARTER_90D,
        entry_add_budget_rule=BUDGET_RULE_70_15_15_LADDER,
        stop_loss_rule=STOP_LOSS_NONE,
        use_config_stop_loss_profiles=False,
        relative_strength_rule=relative_strength_rule,
        volatility_strategy_rules=volatility_strategy_rules,
        description=description or "baseline-v2.4 信号、门控和 70/15/15 执行，但关闭止损和 90 日最大持有。",
    )


def relative_strength_no_risk_experiments() -> list[AblationExperimentConfig]:
    """First layer: isolate RS selection value without stop-loss/max-holding exits."""

    return [
        no_risk_v2_4_control_experiment(),
        no_risk_v2_4_control_experiment(
            name="rs_20_60_120_no_risk",
            label="RS收益排序",
            relative_strength_rule=RS_20_60_120_RANK,
            description="无风控对照 + 20/60/120 日收益综合排序。",
        ),
        no_risk_v2_4_control_experiment(
            name="rs_excess_benchmark_no_risk",
            label="RS超额排序",
            relative_strength_rule=RS_EXCESS_BENCHMARK_RANK,
            description="无风控对照 + 相对市场基准超额收益排序。",
        ),
        no_risk_v2_4_control_experiment(
            name="rs_top_40_no_risk",
            label="RS前40%",
            relative_strength_rule=RS_TOP_40_FILTER,
            description="无风控对照 + 只允许综合强弱前 40% 的 BUY。",
        ),
    ]


def relative_strength_production_experiments() -> list[AblationExperimentConfig]:
    """Second layer: compare RS candidates against full baseline-v2.4."""

    return [
        production_v2_4_experiment(),
        production_v2_4_experiment(
            name="rs_20_60_120_prod",
            label="RS收益排序",
            relative_strength_rule=RS_20_60_120_RANK,
            description="baseline-v2.4 + 20/60/120 日收益综合排序。",
        ),
        production_v2_4_experiment(
            name="rs_excess_benchmark_prod",
            label="RS超额排序",
            relative_strength_rule=RS_EXCESS_BENCHMARK_RANK,
            description="baseline-v2.4 + 相对市场基准超额收益排序。",
        ),
        production_v2_4_experiment(
            name="rs_top_40_prod",
            label="RS前40%",
            relative_strength_rule=RS_TOP_40_FILTER,
            description="baseline-v2.4 + 只允许综合强弱前 40% 的 BUY。",
        ),
    ]


def volatility_strategy_no_risk_experiments() -> list[AblationExperimentConfig]:
    """First layer: isolate volatility-scoped execution rules without risk exits."""

    return [
        no_risk_v2_4_control_experiment(
            name="control_no_risk",
            label="对照无风控",
        ),
        no_risk_v2_4_control_experiment(
            name="vol_high_strict_no_risk",
            label="高波严格",
            volatility_strategy_rules=(VOL_HIGH_STRICT,),
            description="无风控对照 + 高波动 ETF 严格建仓/加仓 score。",
        ),
        no_risk_v2_4_control_experiment(
            name="vol_low_lenient_no_risk",
            label="低波宽加",
            volatility_strategy_rules=(VOL_LOW_LENIENT_ADD,),
            description="无风控对照 + 低波动 ETF 放宽加仓 score。",
        ),
        no_risk_v2_4_control_experiment(
            name="vol_split_no_risk",
            label="高严低宽",
            volatility_strategy_rules=(VOL_HIGH_STRICT, VOL_LOW_LENIENT_ADD),
            description="无风控对照 + 高波严格、低波宽加的组合规则。",
        ),
    ]


def volatility_strategy_production_experiments() -> list[AblationExperimentConfig]:
    """Second layer: compare volatility-scoped execution rules against v2.4."""

    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="新基线：70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有。",
        ),
        production_v2_4_experiment(
            name="vol_high_strict_prod",
            label="高波严格",
            volatility_strategy_rules=(VOL_HIGH_STRICT,),
            description=(
                "baseline-v2.4 风控和止损口径不变，仅提高高波动 ETF "
                "建仓/加仓 score 阈值。"
            ),
        ),
        production_v2_4_experiment(
            name="vol_low_lenient_prod",
            label="低波宽加",
            volatility_strategy_rules=(VOL_LOW_LENIENT_ADD,),
            description=(
                "baseline-v2.4 风控和止损口径不变，仅放宽低波动 ETF "
                "两阶加仓 score 阈值。"
            ),
        ),
        production_v2_4_experiment(
            name="vol_split_prod",
            label="高严低宽",
            volatility_strategy_rules=(VOL_HIGH_STRICT, VOL_LOW_LENIENT_ADD),
            description=(
                "baseline-v2.4 风控和止损口径不变，高波动 ETF 严格入场/加仓，"
                "低波动 ETF 放宽加仓。"
            ),
        ),
    ]


def high_vol_profile_strategy_experiments() -> list[AblationExperimentConfig]:
    """Compare baseline-v2.4 with bottom-layer high-volatility strategy candidates."""

    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="高波动分组对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="high_vol_signal_baseline_risk",
            label="高波新信号",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description="高波动新底层信号 + baseline-v2.4 风控/止损/90日持有。",
        ),
        production_v2_4_experiment(
            name="high_vol_signal_trend_risk",
            label="高波新信号+风控",
            max_holding_days=None,
            stop_loss_rule=STOP_LOSS_NONE,
            use_config_stop_loss_profiles=False,
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            experimental_risk_profile=RISK_PROFILE_HIGH_VOL_TREND,
            description="高波动新底层信号 + ATR 初始止损 + 盈利后移动止损 + 趋势转弱退出。",
        ),
    ]


def low_vol_profile_strategy_experiments() -> list[AblationExperimentConfig]:
    """Compare baseline-v2.4 with bottom-layer low-volatility strategy candidates."""

    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="低波动分组对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="low_vol_signal_baseline_risk",
            label="低波新信号",
            experimental_signal_profile=SIGNAL_PROFILE_LOW_VOL_STABLE,
            description="低波动新底层信号 + baseline-v2.4 风控/止损/90日持有。",
        ),
        production_v2_4_experiment(
            name="low_vol_signal_structure_risk",
            label="低波新信号+风控",
            max_holding_days=180,
            stop_loss_rule=STOP_LOSS_NONE,
            use_config_stop_loss_profiles=False,
            experimental_signal_profile=SIGNAL_PROFILE_LOW_VOL_STABLE,
            experimental_risk_profile=RISK_PROFILE_LOW_VOL_STRUCTURE,
            description="低波动新底层信号 + 结构破坏退出 + -12% 灾难止损 + 180日持有。",
        ),
    ]


def high_vol_mixed_strategy_experiments() -> list[AblationExperimentConfig]:
    """Validate high-vol new signal in the full ETF pool."""

    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="全池对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="mixed_high_vol_signal",
            label="高波新信号混合",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description=(
                "全池混合候选：high_vol 使用高波新底层信号，low_vol 保持 baseline-v2.4；"
                "风控、止损、90日持有和 70/15/15 执行全部沿用 baseline-v2.4。"
            ),
        ),
    ]


def high_vol_frequency_single_experiments() -> list[AblationExperimentConfig]:
    """Single-factor frequency controls on top of the high-vol mixed signal."""

    rules = [
        HIGH_VOL_STOP12,
        HIGH_VOL_BUY_CONFIRM_2,
        HIGH_VOL_BUY_CONFIRM_3,
        HIGH_VOL_ADD_INTERVAL_10,
        HIGH_VOL_SELL_CONFIRM_2,
        HIGH_VOL_SELL_CONFIRM_3,
        HIGH_VOL_MIN_HOLD_5,
        HIGH_VOL_MIN_HOLD_10,
        HIGH_VOL_MAX_POS_6,
    ]
    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="全池对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="mixed_high_vol_signal",
            label="高波新信号混合",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description="high_vol 使用高波新底层信号，low_vol 保持 baseline-v2.4。",
        ),
        *[
            production_v2_4_experiment(
                name=rule.name,
                label=rule.label,
                experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
                high_vol_frequency_rule=rule,
                description=f"高波新信号混合 + {rule.description}",
            )
            for rule in rules
        ],
    ]


def high_vol_frequency_combo_experiments() -> list[AblationExperimentConfig]:
    """Combination frequency controls selected for second-layer validation."""

    rules = [
        HIGH_VOL_BUY2_ADD10,
        HIGH_VOL_BUY2_SELL2,
        HIGH_VOL_BUY2_HOLD5_ADD10,
        HIGH_VOL_BUY2_MAX6,
    ]
    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="全池对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="mixed_high_vol_signal",
            label="高波新信号混合",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description="high_vol 使用高波新底层信号，low_vol 保持 baseline-v2.4。",
        ),
        *[
            production_v2_4_experiment(
                name=rule.name,
                label=rule.label,
                experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
                high_vol_frequency_rule=rule,
                description=f"高波新信号混合 + {rule.description}",
            )
            for rule in rules
        ],
    ]


def high_vol_quality_single_experiments() -> list[AblationExperimentConfig]:
    """Single-factor trade-quality controls on top of the high-vol mixed signal."""

    rules = [
        HIGH_VOL_QUALITY_SCORE55,
        HIGH_VOL_QUALITY_MOMENTUM,
        HIGH_VOL_QUALITY_DAILY_TOP2,
        HIGH_VOL_QUALITY_BUDGET_TIER,
        HIGH_VOL_QUALITY_ADD_STRICT,
    ]
    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="全池对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="mixed_high_vol_signal",
            label="高波新信号混合",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description="high_vol 使用高波新底层信号，low_vol 保持 baseline-v2.4。",
        ),
        production_v2_4_experiment(
            name="high_vol_stop12_reference",
            label="高波止损12%",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            high_vol_frequency_rule=HIGH_VOL_STOP12,
            description="高波新信号混合 + high_vol 止损阈值调整为 -12%，作为质量控制前的风险口径参考。",
        ),
        *[
            production_v2_4_experiment(
                name=rule.name,
                label=rule.label,
                experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
                high_vol_quality_rule=rule,
                description=f"高波新信号混合 + {rule.description}",
            )
            for rule in rules
        ],
    ]


def high_vol_quality_combo_experiments() -> list[AblationExperimentConfig]:
    """Combination trade-quality controls selected for second-layer validation."""

    rules = [
        HIGH_VOL_QUALITY_SCORE_TOP2,
        HIGH_VOL_QUALITY_SCORE_BUDGET,
        HIGH_VOL_QUALITY_COMPOSITE,
    ]
    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="全池对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="mixed_high_vol_signal",
            label="高波新信号混合",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description="high_vol 使用高波新底层信号，low_vol 保持 baseline-v2.4。",
        ),
        *[
            production_v2_4_experiment(
                name=rule.name,
                label=rule.label,
                experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
                high_vol_quality_rule=rule,
                description=f"高波新信号混合 + {rule.description}",
            )
            for rule in rules
        ],
    ]


def high_vol_quality_tier_sensitivity_experiments() -> list[AblationExperimentConfig]:
    """Parameter sensitivity checks for high-vol quality-tier position sizing."""

    rules = [
        HIGH_VOL_QUALITY_BUDGET_TIER,
        HIGH_VOL_QUALITY_TIER_MILD,
        HIGH_VOL_QUALITY_TIER_STRICT,
        HIGH_VOL_QUALITY_TIER_DEFENSIVE,
    ]
    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="全池对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="mixed_high_vol_signal",
            label="高波新信号混合",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description="high_vol 使用高波新底层信号，low_vol 保持 baseline-v2.4。",
        ),
        *[
            production_v2_4_experiment(
                name=rule.name,
                label=rule.label,
                experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
                high_vol_quality_rule=rule,
                description=f"高波新信号混合 + {rule.description}",
            )
            for rule in rules
        ],
    ]


def high_vol_quality_tier_candidate_experiments() -> list[AblationExperimentConfig]:
    """Focused baseline/mixed/current-tier comparison for robustness attribution."""

    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name="mixed_high_vol_signal",
            label="高波新信号混合",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            description="high_vol 使用高波新底层信号，low_vol 保持 baseline-v2.4。",
        ),
        production_v2_4_experiment(
            name=HIGH_VOL_QUALITY_BUDGET_TIER.name,
            label=HIGH_VOL_QUALITY_BUDGET_TIER.label,
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
            description=f"高波新信号混合 + {HIGH_VOL_QUALITY_BUDGET_TIER.description}",
        ),
    ]


def portfolio_risk_control_experiments() -> list[AblationExperimentConfig]:
    """Portfolio-level risk controls on top of the full-pool quality-tier anchor."""

    single_rules = [
        PORTFOLIO_RISK_SINGLE_25,
        PORTFOLIO_RISK_TOTAL_85,
        PORTFOLIO_RISK_HIGH_VOL_25,
        PORTFOLIO_RISK_HIGH_VOL_20,
        PORTFOLIO_RISK_MAX_POSITIONS_10,
        PORTFOLIO_RISK_HIGH_VOL_COUNT_4,
    ]
    combo_rules = [
        PORTFOLIO_RISK_MODERATE,
        PORTFOLIO_RISK_CONSERVATIVE,
    ]
    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="对照：baseline-v2.4 完整生产口径。",
        ),
        production_v2_4_experiment(
            name=HIGH_VOL_QUALITY_BUDGET_TIER.name,
            label="全池质量分层",
            experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
            high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
            description="组合风控锚点：high_vol 使用新底层信号和质量分层仓位，low_vol 保持 baseline-v2.4。",
        ),
        *[
            production_v2_4_experiment(
                name=rule.name,
                label=rule.label,
                experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
                high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
                portfolio_risk_rule=rule,
                description=f"全池质量分层 + {rule.description}",
            )
            for rule in single_rules
        ],
        *[
            production_v2_4_experiment(
                name=rule.name,
                label=rule.label,
                experimental_signal_profile=SIGNAL_PROFILE_HIGH_VOL_BALANCED,
                high_vol_quality_rule=HIGH_VOL_QUALITY_BUDGET_TIER,
                portfolio_risk_rule=rule,
                description=f"全池质量分层 + {rule.description}",
            )
            for rule in combo_rules
        ],
    ]


def portfolio_risk_control_single_experiments() -> list[AblationExperimentConfig]:
    """Single-factor portfolio risk controls for attribution."""

    experiments = portfolio_risk_control_experiments()
    return experiments[:8]


def portfolio_risk_control_combo_experiments() -> list[AblationExperimentConfig]:
    """Combined portfolio risk controls selected for validation."""

    experiments = portfolio_risk_control_experiments()
    return experiments[:2] + experiments[8:]


def reentry_rule_ablation_experiments() -> list[AblationExperimentConfig]:
    """Return stop-loss reentry filter experiments on top of the v2.4 baseline."""

    rules = [
        REENTRY_COOLDOWN_10,
        REENTRY_COOLDOWN_20,
        REENTRY_SCORE_60,
        REENTRY_SCORE_65,
        REENTRY_PRICE_RECLAIM,
        REENTRY_TREND_REPAIR,
        REENTRY_COMPOSITE,
    ]
    experiments = [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="新基线：70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有。",
        )
    ]
    experiments.extend(
        production_v2_4_experiment(
            name=rule.name,
            label=rule.label,
            reentry_rule=rule,
            description=f"新基线 + 止损后再入场过滤：{rule.description}",
        )
        for rule in rules
    )
    return experiments


def trend_reentry_segment_experiments() -> list[AblationExperimentConfig]:
    """Return the focused baseline-v2.4 vs trend-repair comparison."""

    return [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="新基线：70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有。",
        ),
        production_v2_4_experiment(
            name="candidate_v2_5_trend_reentry",
            label="趋势修复",
            reentry_rule=REENTRY_TREND_REPAIR,
            description="v2.5候选：baseline-v2.4 + 止损后趋势修复再入场规则。",
        ),
    ]


def high_vol_reentry_cooldown_experiments() -> list[AblationExperimentConfig]:
    """Return high-volatility stop-loss reentry cooldown experiments."""

    rules = [
        REENTRY_HIGH_VOL_COOLDOWN_10T,
        REENTRY_HIGH_VOL_COOLDOWN_15T,
        REENTRY_HIGH_VOL_COOLDOWN_20T,
        REENTRY_HIGH_VOL_COOLDOWN_30T,
        REENTRY_A_SHARE_HIGH_VOL_COOLDOWN_20T,
        REENTRY_LOW_VOL_COOLDOWN_20T,
    ]
    experiments = [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="新基线：70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有。",
        )
    ]
    experiments.extend(
        production_v2_4_experiment(
            name=rule.name,
            label=rule.label,
            reentry_rule=rule,
            description=f"新基线 + 止损后再入场冷静期：{rule.description}",
        )
        for rule in rules
    )
    return experiments


def high_vol_reentry_stop_price_experiments() -> list[AblationExperimentConfig]:
    """Return high-volatility stop-price reclaim reentry experiments."""

    rules = [
        REENTRY_HIGH_VOL_PRICE_ABOVE_STOP,
        REENTRY_A_SHARE_HIGH_VOL_PRICE_ABOVE_STOP,
        REENTRY_LOW_VOL_PRICE_ABOVE_STOP,
    ]
    experiments = [
        production_v2_4_experiment(
            name="baseline_v2_4_segment_stop",
            label="baseline-v2.4",
            description="新基线：70/15/15阶梯 + 分市场/分波动止损 + 90日最大持有。",
        )
    ]
    experiments.extend(
        production_v2_4_experiment(
            name=rule.name,
            label=rule.label,
            reentry_rule=rule,
            description=f"新基线 + 止损价再入场约束：{rule.description}",
        )
        for rule in rules
    )
    return experiments


def get_ablation_experiments(matrix: str) -> tuple[list[AblationExperimentConfig], str]:
    """Return experiments and baseline name for a supported matrix."""

    if matrix == "default":
        return default_ablation_experiments(), "baseline_full_gate"
    if matrix == "preferred-cycle":
        return preferred_cycle_ablation_experiments(), "preferred_baseline_full_gate"
    if matrix == "add-rules":
        return add_rules_ablation_experiments(), "preferred_add_baseline"
    if matrix == "entry-add-budget":
        return entry_add_budget_ablation_experiments(), "budget_100_no_add"
    if matrix == "stop-loss-rules":
        return stop_loss_ablation_experiments(), "stop_fixed_8"
    if matrix == "candidate-comparison":
        return candidate_comparison_experiments(), "baseline_v2_3_gate_lite_regime"
    if matrix == "reentry-rules":
        return reentry_rule_ablation_experiments(), "baseline_v2_4_segment_stop"
    if matrix == "trend-reentry-segments":
        return trend_reentry_segment_experiments(), "baseline_v2_4_segment_stop"
    if matrix == "high-vol-reentry-cooldown":
        return high_vol_reentry_cooldown_experiments(), "baseline_v2_4_segment_stop"
    if matrix == "high-vol-reentry-stop-price":
        return high_vol_reentry_stop_price_experiments(), "baseline_v2_4_segment_stop"
    if matrix == "high-vol-quality-control":
        return high_vol_quality_single_experiments(), "baseline_v2_4_segment_stop"
    if matrix == "high-vol-quality-tier-robustness":
        return high_vol_quality_tier_sensitivity_experiments(), "baseline_v2_4_segment_stop"
    if matrix == "portfolio-risk-control":
        return portfolio_risk_control_experiments(), "high_vol_quality_budget_tier"
    raise ValueError(f"未知消融实验集: {matrix}")



