"""技术指标单元测试：纯 DataFrame in/out，无数据库依赖。"""

import pandas as pd
import pytest

from src.indicators import Bollinger, VolumeIndicator, RSI


def _make_df(values: list[float], extra_col: dict | None = None) -> pd.DataFrame:
    """构造测试用 DataFrame，date 列 + close 列 + 可选额外列。"""
    data = {"date": [f"2026-01-{i+1:02d}" for i in range(len(values))], "close": values}
    if extra_col:
        data.update(extra_col)
    return pd.DataFrame(data)


# ── Bollinger ──


class TestBollinger:
    def test_constant_price(self):
        """相同收盘价：bb_width ≈ 0，bb_mid = 该值。"""
        df = _make_df([100.0] * 30)
        result = Bollinger(window=20, num_std=2.0).calculate(df)

        last = result.iloc[-1]
        assert last["bb_mid"] == pytest.approx(100.0)
        assert last["bb_lower"] == pytest.approx(100.0)
        assert last["bb_upper"] == pytest.approx(100.0)
        assert last["bb_width"] == pytest.approx(0.0, abs=1e-6)

    def test_output_columns(self):
        df = _make_df([100.0 + i for i in range(30)])
        result = Bollinger().calculate(df)
        assert list(result.columns) == ["date", "bb_mid", "bb_upper", "bb_lower", "bb_width"]

    def test_window_nan(self):
        """前 window-1 行应为 NaN。"""
        df = _make_df([100.0] * 25)
        result = Bollinger(window=20).calculate(df)
        assert result["bb_mid"].iloc[18] != result["bb_mid"].iloc[18]  # NaN 自我不等
        assert pd.notna(result["bb_mid"].iloc[19])


# ── VolumeIndicator ──


class TestVolumeIndicator:
    def test_constant_volume(self):
        """恒定成交量：vol_ma20 = 成交量，vol_ratio = 1.0。"""
        df = _make_df(
            [100.0] * 30, extra_col={"volume": [5000.0] * 30}
        )
        result = VolumeIndicator(window=20).calculate(df)

        last = result.iloc[-1]
        assert last["vol_ma20"] == pytest.approx(5000.0)
        assert last["vol_ratio"] == pytest.approx(1.0)

    def test_volume_spike(self):
        """今日放量 3 倍。"""
        volumes = [1000] * 29 + [3000]
        prices = [100.0] * 30
        df = _make_df(prices, extra_col={"volume": volumes})
        result = VolumeIndicator(window=20).calculate(df)

        last = result.iloc[-1]
        assert last["vol_ma20"] == pytest.approx(1100.0)
        assert last["vol_ratio"] == pytest.approx(3000 / 1100.0)

    def test_output_columns(self):
        df = _make_df([100.0] * 30, extra_col={"volume": [1000.0] * 30})
        result = VolumeIndicator().calculate(df)
        assert list(result.columns) == ["date", "vol_ma20", "vol_ratio"]


# ── RSI ──


class TestRSI:
    def test_all_up(self):
        """14 天连续涨 1 元：RSI 应接近 100。"""
        df = _make_df([100.0 + i for i in range(30)])
        result = RSI(period=14).calculate(df)
        last = result.iloc[-1]
        assert last["rsi"] > 99.0

    def test_all_down(self):
        """14 天连续跌 1 元：RSI 应接近 0。"""
        df = _make_df([100.0 - i for i in range(30)])
        result = RSI(period=14).calculate(df)
        last = result.iloc[-1]
        assert last["rsi"] < 1.0

    def test_output_columns(self):
        df = _make_df([100.0] * 30)
        result = RSI().calculate(df)
        assert list(result.columns) == ["date", "rsi"]
