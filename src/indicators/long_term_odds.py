"""长期赔率因子 — 基于 ETF 自身历史价格构建开仓赔率门控。

不依赖 PE/PB 等外部估值数据，仅使用 quote 表中的 OHLCV + NAV 字段。
回答：当前这只 ETF 的长期入场赔率 — 便宜 / 中性 / 偏贵？
输出 CHEAP / FAIR / EXPENSIVE 三态门控，不直接产生 BUY/SELL。
"""

import numpy as np
import pandas as pd

from .base import BaseIndicator


class LongTermOdds(BaseIndicator):
    """长期赔率因子，基于滚动窗口内的历史价格行为评估当前赔率。

    计算 5 个原子指标（价格分位/回撤/Z-score/持有胜率/风险惩罚），
    加权求和得到 -100~+100 综合评分，映射为三态门控。

    关键参数:
        L=756（约 3 年交易日）— 长期滚动窗口
        H=252（约 1 年交易日）— 持有期窗口
    """

    def __init__(
        self,
        L: int = 756,
        H: int = 252,
        premium_threshold: float = 0.015,
    ):
        """初始化长期赔率因子。

        Args:
            L: 长期滚动窗口（交易日），默认 756（约 3 年）
            H: 持有期窗口（交易日），默认 252（约 1 年）
            premium_threshold: 溢价硬过滤阈值，默认 1.5%
        """
        self.L = L
        self.H = H
        self.premium_threshold = premium_threshold

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算长期赔率指标。

        输入 DataFrame 须包含 date/close 列，可选 nav/premium_rate。
        价格基准 P_t = nav（若存在且非空）else close。

        Args:
            df: 行情数据，按 date 升序排列

        Returns:
            含 date + 9 列 odds 指标的 DataFrame
        """
        n = len(df)
        result = df[["date"]].copy()

        # ── 构建价格基准 P_t ──
        if "nav" in df.columns:
            price = df["nav"].copy()
            # nav 缺失时回退到 close
            price = price.fillna(df["close"])
        else:
            price = df["close"].copy()

        # ── 动态窗口：短历史 ETF 自适应缩放 L ──
        if n < self.H + 252:
            # 不足 2 年数据，无法可靠评估赔率，全列标记 INSUFFICIENT
            return self._insufficient_result(result, n)

        L_actual = min(self.L, n - self.H)

        # ── 1. 历史价格分位 ──
        self._calc_price_percentile(result, price, L_actual)

        # ── 2. 回撤赔率 ──
        self._calc_drawdown(result, price, L_actual)

        # ── 3. 长期均值偏离（Z-score） ──
        self._calc_zscore(result, price, L_actual)

        # ── 4. 历史持有胜率 ──
        self._calc_holding(result, price, L_actual, self.H)

        # ── 5. 风险惩罚 ──
        self._calc_risk_penalty(result, price, L_actual)

        # ── 6. 综合评分 + 状态映射 ──
        self._composite_score(result)

        # ── 7. 溢价硬过滤 ──
        self._premium_filter(result, df.get("premium_rate", pd.Series([None] * n)))

        # 前 L_actual + H - 1 行因滚动窗口不足，各子指标内部已设 NaN，
        # 此处不再额外处理

        return result

    # ── 原子指标子方法 ──

    def _calc_price_percentile(
        self, result: pd.DataFrame, price: pd.Series, L: int
    ) -> None:
        """历史价格分位：当前 P_t 在过去 L 天中的百分位。

        price_pct ∈ [~1/L, 1.0]，越低越便宜。
        S_price ∈ [-1, 1]，正值为便宜（低于中枢），负值为偏贵（高于中枢）。
        """
        # 滚动窗口内最后一个值的百分位秩
        def _last_pct_rank(window: np.ndarray) -> float:
            last = window[-1]
            return float((window <= last).sum() / len(window))

        result["odds_price_pct"] = (
            price.rolling(L, min_periods=L)
            .apply(_last_pct_rank, raw=True)
        )
        # S_price = (0.5 - price_pct) * 2，clamp 到 [-1, 1]
        s_price = (0.5 - result["odds_price_pct"]) * 2.0
        result["_s_price"] = s_price.clip(-1.0, 1.0)

    def _calc_drawdown(
        self, result: pd.DataFrame, price: pd.Series, L: int
    ) -> None:
        """回撤赔率：当前价格相对 L 天高点的回撤幅度。

        drawdown ∈ (-∞, 0]，越低说明回撤越大。
        S_drawdown ∈ [0, 1]，回撤越深分数越高（反弹赔率越大）。
        """
        rolling_high = price.rolling(L, min_periods=L).max()
        result["odds_drawdown"] = price / rolling_high - 1.0
        # S_drawdown = abs(drawdown) / 0.30，clamp 到 [0, 1]
        dd_abs = result["odds_drawdown"].abs()
        result["_s_drawdown"] = (dd_abs / 0.30).clip(0.0, 1.0)

    def _calc_zscore(
        self, result: pd.DataFrame, price: pd.Series, L: int
    ) -> None:
        """长期均值偏离：当前 P_t 相对 L 天均值的标准化偏离。

        zscore 无界，负值表示低于均值（便宜）。
        S_z ∈ [-1, 1]，负 z → 正 S_z（低于均值 = 便宜信号）。
        """
        ma = price.rolling(L, min_periods=L).mean()
        std = price.rolling(L, min_periods=L).std()
        # 避免除零：std 极小（横盘）时 z → 0
        std_safe = std.replace(0.0, np.nan)
        result["odds_zscore"] = (price - ma) / std_safe
        # S_z = clamp(-z / 2, -1, 1)
        s_z = -result["odds_zscore"] / 2.0
        result["_s_z"] = s_z.clip(-1.0, 1.0)

    def _calc_holding(
        self, result: pd.DataFrame, price: pd.Series, L: int, H: int
    ) -> None:
        """历史持有胜率：L-H 窗口内任意时点买入并持有 1 年的表现。

        无未来函数 —— 只统计 i+H <= t 的已完成持有期。
        窗口长度 = L - H（保证至少一个完整持有期可被观察到）。

        S_hold ∈ [-1, 1]，正值为历史持有体验好（当前赔率偏高），
        负值为历史持有体验差（当前赔率偏低）。
        """
        # 前向 H 日收益率：forward_ret[i] = P[i+H] / P[i] - 1
        forward_ret = price.shift(-H) / price - 1.0

        win_L = L - H  # 持有评分滚动窗口长度
        if win_L < 1:
            # 极端情况：L <= H，无法计算持有评分
            result["odds_hold_winrate_1y"] = np.nan
            result["odds_hold_avg_return_1y"] = np.nan
            result["_s_hold"] = np.nan
            return

        # rolling(win_L) 在 forward_ret 上计算，再 shift(H) 对齐到 t
        roll_winrate = (forward_ret > 0).rolling(win_L, min_periods=win_L).mean()
        roll_avgret = forward_ret.rolling(win_L, min_periods=win_L).mean()

        result["odds_hold_winrate_1y"] = roll_winrate.shift(H)
        result["odds_hold_avg_return_1y"] = roll_avgret.shift(H)

        # S_winrate = clamp((winrate - 0.5) * 4, -1, 1)
        s_wr = (result["odds_hold_winrate_1y"] - 0.5) * 4.0
        # S_avg_return = clamp(avg_return / 0.20, -1, 1)
        s_ar = result["odds_hold_avg_return_1y"] / 0.20
        # S_hold = 0.6 * S_winrate + 0.4 * S_avg_return
        result["_s_hold"] = (
            0.6 * s_wr.clip(-1.0, 1.0) + 0.4 * s_ar.clip(-1.0, 1.0)
        )

    def _calc_risk_penalty(
        self, result: pd.DataFrame, price: pd.Series, L: int
    ) -> None:
        """风险惩罚：年化波动率 + 最大回撤的惩罚项。

        P_risk ∈ [0, 1]，越高说明风险越大。
        S_risk ∈ [-1, 0]，总是扣分或零分（不奖励高风险）。

        max_dd 需要两层 rolling（先算逐日回撤再取 L 窗口最差值），
        理论需要 2*L 行才稳定。此处用 min_periods=H（约 1 年）折中，
        数据越多精度越高，但不会因为窗口不足返回全 NaN。
        """
        H = self.H
        # 日收益率
        r = price.pct_change()
        # 年化波动率（滚动，最小 H 日）
        vol_ann = r.rolling(L, min_periods=H).std() * np.sqrt(252)
        # L 窗口内最大回撤：先算逐日回撤（从滚动高点），再取窗口内最差值
        rolling_peak = price.rolling(L, min_periods=H).max()
        dd = price / rolling_peak - 1.0
        # dd 的滚动最小值 — 不要求满 L 才有值，H 日后即可出结果
        max_dd = dd.rolling(L, min_periods=H).min()

        # P_risk = 0.5 * clamp((vol - 0.20) / 0.20, 0, 1)
        #        + 0.5 * clamp((abs(max_dd) - 0.30) / 0.30, 0, 1)
        p_vol = ((vol_ann - 0.20) / 0.20).clip(0.0, 1.0)
        p_dd = ((max_dd.abs() - 0.30) / 0.30).clip(0.0, 1.0)
        p_risk = 0.5 * p_vol + 0.5 * p_dd

        result["odds_risk_penalty"] = -p_risk  # S_risk ∈ [-1, 0]
        result["_s_risk"] = -p_risk

    def _composite_score(self, result: pd.DataFrame) -> None:
        """加权求和 + 状态映射。

        odds_score = 0.30*S_price + 0.20*S_drawdown + 0.20*S_z
                    + 0.20*S_hold + 0.10*S_risk
        映射: >= +30 → CHEAP, <= -30 → EXPENSIVE, 其余 → FAIR
        """
        # 各子指标用 fillna(0) 兜底，避免单一子指标因窗口不足导致
        # 总分全列 NaN（如 risk_penalty 需要更多数据才能出值）
        s_price = result["_s_price"].fillna(0.0)
        s_drawdown = result["_s_drawdown"].fillna(0.0)
        s_z = result["_s_z"].fillna(0.0)
        s_hold = result["_s_hold"].fillna(0.0)
        s_risk = result["_s_risk"].fillna(0.0)

        result["odds_score"] = (
            0.30 * s_price
            + 0.20 * s_drawdown
            + 0.20 * s_z
            + 0.20 * s_hold
            + 0.10 * s_risk
        ) * 100.0  # 缩放到 [-100, 100]

        # 状态映射
        conditions = [
            result["odds_score"] >= 30,
            result["odds_score"] <= -30,
        ]
        choices = ["CHEAP", "EXPENSIVE"]
        result["odds_state"] = np.select(
            conditions, choices, default="FAIR"
        )
        # 核心子指标不可用时（滚动窗口数据不足），评分和状态均置空
        # 使用 odds_price_pct 作为标志 — 它需要满 L 天窗口才有值
        insufficient = result["odds_price_pct"].isna()
        result.loc[insufficient, "odds_score"] = np.nan
        result.loc[insufficient, "odds_state"] = np.nan

        # 删除内部辅助列
        for col in ["_s_price", "_s_drawdown", "_s_z", "_s_hold", "_s_risk"]:
            del result[col]

    def _premium_filter(
        self,
        result: pd.DataFrame,
        premium_rate: pd.Series,
    ) -> None:
        """溢价硬过滤：溢价率 >= 1.5% 标记为 blocked。

        高溢价 = 场内价格虚高 → 开仓赔率被高估 → 拦截买入。
        premium_rate 为 NaN 时默认不拦截（blocked = False）。
        """
        blocked = premium_rate.fillna(0.0) >= self.premium_threshold
        result["odds_premium_blocked"] = blocked

    @staticmethod
    def _insufficient_result(result: pd.DataFrame, n: int) -> pd.DataFrame:
        """短历史 ETF 的统一返回：全列 NaN，仅 state 标记 INSUFFICIENT。"""
        for col in [
            "odds_score",
            "odds_state",
            "odds_price_pct",
            "odds_drawdown",
            "odds_zscore",
            "odds_hold_winrate_1y",
            "odds_hold_avg_return_1y",
            "odds_risk_penalty",
            "odds_premium_blocked",
        ]:
            result[col] = np.nan
        result["odds_state"] = "INSUFFICIENT"
        return result
