"""双均线交叉策略（MVP）。"""

import pandas as pd

from .base import BaseStrategy


class MaCrossStrategy(BaseStrategy):
    """MA20/MA60 金叉买入，死叉卖出。

    params:
        ma_short: 短期均线周期，默认 20
        ma_long:  长期均线周期，默认 60
    """

    def __init__(self, ma_short: int = 20, ma_long: int = 60):
        """初始化均线参数与策略版本号。"""
        self.ma_short = ma_short
        self.ma_long = ma_long
        self.version = "1.0"

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """基于 MA 金叉/死叉生成 BUY/SELL 信号。

        Args:
            df: 含 ma{short}、ma{long} 列的指标 DataFrame

        Returns:
            DataFrame，columns = [code, date, signal, strategy_version, signal_meta]，
            signal 可选值为 BUY / SELL / HOLD

        Example:
            >>> strategy = MaCrossStrategy(20, 60)
            >>> signals = strategy.generate(indicator_df)
            >>> signals[signals["signal"] != "HOLD"].head()
        """
        df = df.sort_values(["code", "date"]).reset_index(drop=True)

        results = []
        for code in df["code"].unique():
            mask = df["code"] == code
            code_df = df[mask].sort_values("date").reset_index(drop=True)

            ma_s = code_df[f"ma{self.ma_short}"]
            ma_l = code_df[f"ma{self.ma_long}"]
            ma_s_prev = ma_s.shift(1)
            ma_l_prev = ma_l.shift(1)

            golden = (ma_s_prev <= ma_l_prev) & (ma_s > ma_l)
            death = (ma_s_prev > ma_l_prev) & (ma_s <= ma_l)
            nan_mask = ma_s.isna() | ma_l.isna()

            signal = pd.Series("HOLD", index=code_df.index)
            signal[golden & ~nan_mask] = "BUY"
            signal[death & ~nan_mask] = "SELL"

            trend = pd.Series("flat", index=code_df.index)
            trend[ma_s > ma_l] = "up"
            trend[ma_s < ma_l] = "down"
            trend[nan_mask] = "unknown"

            cross = pd.Series("none", index=code_df.index)
            cross[golden & ~nan_mask] = "golden"
            cross[death & ~nan_mask] = "death"

            meta = [
                {
                    "trend": t,
                    "cross": c,
                    f"ma{self.ma_short}": round(float(s), 4) if pd.notna(s) else None,
                    f"ma{self.ma_long}": round(float(l), 4) if pd.notna(l) else None,
                }
                for t, c, s, l in zip(trend, cross, ma_s, ma_l)
            ]

            results.append(pd.DataFrame({
                "code": code_df["code"],
                "date": code_df["date"],
                "signal": signal.values,
                "strategy_version": self.version,
                "signal_meta": meta,
            }))

        if results:
            return pd.concat(results, ignore_index=True)
        return pd.DataFrame(
            columns=["code", "date", "signal", "strategy_version", "signal_meta"]
        )
