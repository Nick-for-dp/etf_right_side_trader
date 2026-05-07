"""双均线交叉 + MACD 辅助确认策略（v1.1）。"""

import pandas as pd

from .base import BaseStrategy


class MaCrossMacdStrategy(BaseStrategy):
    """MA20/MA60 金叉且 DIF>0 买入，死叉卖出。

    BUY 侧加入 MACD 确认（DIF > 0），过滤无动能假突破；
    SELL 侧不依赖 MACD，跟随趋势反转信号。
    """

    def __init__(self, ma_short: int = 20, ma_long: int = 60):
        self.ma_short = ma_short
        self.ma_long = ma_long
        self.version = "1.1"

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values(["code", "date"]).reset_index(drop=True)

        results = []
        for code in df["code"].unique():
            mask = df["code"] == code
            code_df = df[mask].sort_values("date").reset_index(drop=True)

            ma_s = code_df[f"ma{self.ma_short}"]
            ma_l = code_df[f"ma{self.ma_long}"]
            dif = code_df.get("dif", pd.Series([float("nan")] * len(code_df)))

            ma_s_prev = ma_s.shift(1)
            ma_l_prev = ma_l.shift(1)

            golden = (ma_s_prev <= ma_l_prev) & (ma_s > ma_l)
            death = (ma_s_prev > ma_l_prev) & (ma_s <= ma_l)
            nan_mask = ma_s.isna() | ma_l.isna()

            # 金叉 + DIF > 0 才出 BUY，卖出不受 MACD 限制
            signal = pd.Series("HOLD", index=code_df.index)
            signal[golden & ~nan_mask & (dif > 0)] = "BUY"
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
                    "dif": round(float(d), 4) if pd.notna(d) else None,
                }
                for t, c, s, l, d in zip(trend, cross, ma_s, ma_l, dif)
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
