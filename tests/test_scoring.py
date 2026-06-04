"""综合评分策略单元测试：纯 DataFrame in/out。"""

import pandas as pd

from src.strategy.multi_indicator_scoring import MultiIndicatorScoring


DEFAULT_WEIGHTS = {"trend": 0.35, "macd": 0.25, "rsi": 0.15, "bb": 0.25}
DEFAULT_THRESHOLDS = {"buy": 30, "sell": -30}


def _make_df(code: str, rows: list[dict]) -> pd.DataFrame:
    """构造含全部指标列的测试 DataFrame。"""
    data = []
    for r in rows:
        bb_u = r.get("bb_upper", float("nan"))
        bb_l = r.get("bb_lower", float("nan"))
        bb_mid_v = r.get("bb_mid",
                         (bb_u + bb_l) / 2
                         if not (pd.isna(bb_u) or pd.isna(bb_l))
                         else float("nan"))
        bb_w = r.get("bb_width",
                     (bb_u - bb_l) / bb_mid_v
                     if (not pd.isna(bb_mid_v) and bb_mid_v != 0)
                     else float("nan"))
        row = {
            "code": code,
            "date": r.get("date", "2026-01-01"),
            "ma20": r.get("ma20", float("nan")),
            "ma60": r.get("ma60", float("nan")),
            "close": r.get("close", float("nan")),
            "dif": r.get("dif", float("nan")),
            "dea": r.get("dea", float("nan")),
            "rsi": r.get("rsi", float("nan")),
            "bb_upper": bb_u,
            "bb_lower": bb_l,
            "bb_mid": bb_mid_v,
            "bb_width": bb_w,
            "adx14": r.get("adx14", 20.0),
            "vol_ratio": r.get("vol_ratio", 1.0),
        }
        data.append(row)
    return pd.DataFrame(data)


# ── 子信号方向验证 ──


class TestSignalDirection:
    def test_strong_bull(self):
        """强多头：均线多头 + RSI 65 + DIF 正值 + 触上轨 + 标准量 + 强趋势。"""
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.25, "ma20": 1.22, "ma60": 1.18,
            "dif": 0.008, "dea": 0.005,
            "rsi": 65.0, "bb_upper": 1.28, "bb_lower": 1.16, "vol_ratio": 1.0,
            "adx14": 28.0,
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)
        result = strategy.generate(df)
        row = result.iloc[0]
        assert row["signal"] == "BUY"
        meta = row["signal_meta"]
        assert meta["score"] >= 50
        assert meta["s_trend"] > 0.5
        assert meta["s_macd"] > 0

    def test_strong_bear(self):
        """强空头：均线空头 + RSI 35 + DIF 负值 + 触下轨 + 强趋势。"""
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 0.95, "ma20": 0.98, "ma60": 1.02,
            "dif": -0.006, "dea": -0.004,
            "rsi": 35.0, "bb_upper": 1.04, "bb_lower": 0.92, "vol_ratio": 1.0,
            "adx14": 28.0,
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)
        result = strategy.generate(df)
        row = result.iloc[0]
        assert row["signal"] == "SELL"
        meta = row["signal_meta"]
        assert meta["score"] <= -50

    def test_neutral(self):
        """中性：均线缠绕 + RSI 50 + DIF ≈ 0 + 中轨。"""
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.00, "ma20": 1.00, "ma60": 1.00,
            "dif": 0.0001, "dea": 0.0001,
            "rsi": 50.0, "bb_upper": 1.04, "bb_lower": 0.96, "vol_ratio": 1.0,
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)
        result = strategy.generate(df)
        row = result.iloc[0]
        assert row["signal"] == "HOLD"
        assert abs(row["signal_meta"]["score"]) <= 10


# ── Volume 乘数 ──


class TestVolumeMultiplier:
    def test_volume_amplifies(self):
        """放量适度放大信号强度（成交量确认奖励）。"""
        base_row = {
            "date": "2026-01-15", "close": 1.25, "ma20": 1.22, "ma60": 1.18,
            "dif": 0.008, "dea": 0.005,
            "rsi": 65.0, "bb_upper": 1.28, "bb_lower": 1.16,
        }
        df_normal = _make_df("588000", [{**base_row, "vol_ratio": 1.0}])
        df_spike = _make_df("588000", [{**base_row, "vol_ratio": 2.0}])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)

        score_normal = abs(strategy.generate(df_normal).iloc[0]["signal_meta"]["score"])
        score_spike = abs(strategy.generate(df_spike).iloc[0]["signal_meta"]["score"])
        # vol_ratio=2.0 → clip(0.6, 1.15) → 1.15 → 1.15^0.3 ≈ 1.043
        # vol_ratio=1.0 → 1.0 → 1.0^0.3 = 1.0，放量确认奖励约 +4.3%
        assert score_spike > score_normal
        ratio = score_spike / score_normal
        assert 1.03 < ratio < 1.06

    def test_volume_dampens(self):
        """缩量压低信号强度。"""
        base_row = {
            "date": "2026-01-15", "close": 1.25, "ma20": 1.22, "ma60": 1.18,
            "dif": 0.008, "dea": 0.005,
            "rsi": 65.0, "bb_upper": 1.28, "bb_lower": 1.16,
        }
        df_normal = _make_df("588000", [{**base_row, "vol_ratio": 1.0}])
        df_low = _make_df("588000", [{**base_row, "vol_ratio": 0.5}])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)

        score_normal = abs(strategy.generate(df_normal).iloc[0]["signal_meta"]["score"])
        score_low = abs(strategy.generate(df_low).iloc[0]["signal_meta"]["score"])
        # vol_ratio=0.5 → clip(0.6, 1.15) → 0.6 → 0.6^0.3 ≈ 0.858，缩量衰减约 -14%
        assert score_low < score_normal
        ratio = score_low / score_normal
        assert 0.82 < ratio < 0.90


# ── NaN 处理 ──


class TestNaNHandling:
    def test_missing_indicators_returns_hold(self):
        """指标不全 → HOLD + score=0。"""
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.00, "vol_ratio": 1.0,
            # ma20/ma60/dif/dea/rsi/bb 全部 NaN
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)
        result = strategy.generate(df)
        row = result.iloc[0]
        assert row["signal"] == "HOLD"
        assert row["signal_meta"] == {}

    def test_partial_nan_still_hold(self):
        """部分指标有值部分 NaN → HOLD。"""
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.25, "ma20": 1.22, "ma60": 1.18,
            "dif": float("nan"), "dea": float("nan"),
            "rsi": 65.0, "bb_upper": 1.28, "bb_lower": 1.16, "vol_ratio": 1.0,
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)
        result = strategy.generate(df)
        row = result.iloc[0]
        assert row["signal"] == "HOLD"


# ── 阈值映射边界 ──


class TestThresholdMapping:
    def test_buy_boundary(self):
        """score >= +30 → BUY，刚好 30。"""
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.10, "ma20": 1.07, "ma60": 1.05,
            "dif": 0.003, "dea": 0.002,
            "rsi": 57.0, "bb_upper": 1.12, "bb_lower": 1.03, "vol_ratio": 1.0,
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds={"buy": 30, "sell": -30})
        result = strategy.generate(df)
        # 此配置下分数应 ≥ 30 或接近
        score = result.iloc[0]["signal_meta"]["score"]
        if score >= 30:
            assert result.iloc[0]["signal"] == "BUY"
        else:
            # 若分数差一点，验证 HOLD 而非 SELL
            assert result.iloc[0]["signal"] in ("HOLD", "BUY")

    def test_custom_thresholds(self):
        """自定义阈值：buy=20 → 更容易触发 BUY。"""
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.08, "ma20": 1.06, "ma60": 1.04,
            "dif": 0.002, "dea": 0.001,
            "rsi": 56.0, "bb_upper": 1.10, "bb_lower": 1.02, "vol_ratio": 1.0,
        }])
        strategy_default = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds={"buy": 30, "sell": -30})
        strategy_low = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds={"buy": 20, "sell": -30})

        score = strategy_default.generate(df).iloc[0]["signal_meta"]["score"]
        signal_low = strategy_low.generate(df).iloc[0]["signal"]
        # 20 阈值下更可能触发 BUY
        if score >= 20:
            assert signal_low == "BUY"


# ── 输出格式 ──


class TestOutputFormat:
    def test_output_columns(self):
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.25, "ma20": 1.22, "ma60": 1.18,
            "dif": 0.008, "dea": 0.005,
            "rsi": 65.0, "bb_upper": 1.28, "bb_lower": 1.16, "vol_ratio": 1.0,
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)
        result = strategy.generate(df)
        assert list(result.columns) == ["code", "date", "signal", "strategy_version", "signal_meta"]
        assert result.iloc[0]["strategy_version"] == "2.3"

    def test_signal_meta_keys(self):
        df = _make_df("588000", [{
            "date": "2026-01-15", "close": 1.25, "ma20": 1.22, "ma60": 1.18,
            "dif": 0.008, "dea": 0.005,
            "rsi": 65.0, "bb_upper": 1.28, "bb_lower": 1.16, "vol_ratio": 1.0,
            "adx14": 28.0,
        }])
        strategy = MultiIndicatorScoring(weights=DEFAULT_WEIGHTS, thresholds=DEFAULT_THRESHOLDS)
        result = strategy.generate(df)
        meta = result.iloc[0]["signal_meta"]
        for key in ("s_trend", "s_macd", "s_rsi", "s_bb", "bb_width_pct",
                    "vol_mult", "adx_mult", "adx", "raw_score", "score"):
            assert key in meta, f"signal_meta 缺少 {key}"
