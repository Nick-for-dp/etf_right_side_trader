#!/usr/bin/env python
"""构建 ETF 波动特征矩阵 — 数据驱动的 ETF 分类第一步。

从 indicators 和 quote 表提取 27 只 ETF 的 7 维特征，输出 CSV。
"""

import sys
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.config import load_config
from src.database import init_engine, dispose_engine
from src.database.repository import indicators_repo, quote_repo
from src.service.calendar_service import TradingCalendarService


def main():
    config = load_config()
    engine = init_engine(config.db_url)
    calendar = TradingCalendarService()
    end = date.fromisoformat(calendar.get_previous_trading_day())

    codes = [e.symbol for e in config.etf_list]
    etf_names = {e.symbol: e.name for e in config.etf_list}
    regime_groups = {e.symbol: e.regime_group for e in config.etf_list}
    existing_groups = {e.symbol: e.volatility_group for e in config.etf_list}

    print(f"提取 {len(codes)} 只 ETF 的全量特征，截止 {end}")

    rows = []
    for code in codes:
        row = {
            "code": code,
            "name": etf_names.get(code, code),
            "regime_group": regime_groups.get(code, "unknown"),
            "existing_vol_group": existing_groups.get(code, "unknown"),
        }

        # ── indicators 特征 ──
        inds = indicators_repo.find_by_code_between(code, date(2016, 1, 1), end)
        if inds:
            atr_vals = [
                float(ind.data["atr_pct"])
                for ind in inds
                if ind.data.get("atr_pct") is not None
            ]
            adx_vals = [
                float(ind.data["adx14"])
                for ind in inds
                if ind.data.get("adx14") is not None
            ]
            row["median_atr_pct"] = np.median(atr_vals) if atr_vals else None
            row["p95_atr_pct"] = np.percentile(atr_vals, 95) if atr_vals else None
            row["median_adx"] = np.median(adx_vals) if adx_vals else None
        else:
            row["median_atr_pct"] = None
            row["p95_atr_pct"] = None
            row["median_adx"] = None

        # ── quote 特征 ──
        quotes = quote_repo.find_by_code_in_range(code, date(2016, 1, 1), end)
        if len(quotes) < 20:
            print(f"  {code}: 行情数据不足 ({len(quotes)} 条)，跳过")
            rows.append(row)
            continue

        df = pd.DataFrame(
            [
                {
                    "date": q.date,
                    "close": float(q.close),
                    "volume": float(q.volume),
                }
                for q in quotes
            ]
        ).sort_values("date").reset_index(drop=True)

        # 日收益率
        df["return"] = df["close"].pct_change()
        # 20日滚动波动率（年化）
        df["vol_20d"] = df["return"].rolling(20).std() * np.sqrt(252)
        # 最大回撤
        df["cummax"] = df["close"].cummax()
        df["drawdown"] = df["close"] / df["cummax"] - 1

        row["volatility_20d"] = df["vol_20d"].dropna().median()
        row["max_drawdown"] = df["drawdown"].min()
        row["volume_cv"] = df["volume"].std() / df["volume"].mean() if df["volume"].mean() > 0 else None
        row["return_skew"] = df["return"].dropna().skew()
        row["median_volume"] = df["volume"].median()
        row["trading_days"] = len(df)
        row["avg_daily_return"] = df["return"].dropna().mean()
        row["return_sharpe"] = (
            df["return"].dropna().mean() / df["return"].dropna().std() * np.sqrt(252)
            if df["return"].dropna().std() > 0 else None
        )

        # 趋势稳定性：ADX > 25 的占比（强趋势比例）
        if adx_vals:
            row["strong_trend_pct"] = sum(1 for v in adx_vals if v > 25) / len(adx_vals)
        else:
            row["strong_trend_pct"] = None

        rows.append(row)
        print(f"  {code} {etf_names.get(code, '')}: "
              f"ATRpct_med={row.get('median_atr_pct', 'N/A'):.4f}, "
              f"vol20d={row.get('volatility_20d', 'N/A'):.4f}, "
              f"maxDD={row.get('max_drawdown', 'N/A'):.2%}, "
              f"ADX_med={row.get('median_adx', 'N/A'):.1f}, "
              f"强趋势={row.get('strong_trend_pct', 'N/A')}")

    df_out = pd.DataFrame(rows)
    out_path = os.path.join(os.path.dirname(__file__), "etf_features.csv")
    df_out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n特征矩阵已保存: {out_path}")
    print(f"共 {len(df_out)} 只 ETF")

    # 摘要
    print("\n=== 特征分布摘要 ===")
    num_cols = ["median_atr_pct", "p95_atr_pct", "volatility_20d", "max_drawdown",
                "volume_cv", "return_skew", "median_adx", "strong_trend_pct", "avg_daily_return"]
    for col in num_cols:
        if col in df_out.columns:
            vals = df_out[col].dropna()
            print(f"  {col:20s}: min={vals.min():.4f}, p25={vals.quantile(0.25):.4f}, "
                  f"med={vals.median():.4f}, p75={vals.quantile(0.75):.4f}, max={vals.max():.4f}")

    dispose_engine()


if __name__ == "__main__":
    main()
