import pytest
import numpy as np
import pandas as pd
from src.ta_indicators.ta_core import sma, ema, rsi_ema, vwap, atr


def test_sma():
    series = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    result = sma(series, 3)
    
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == 2.0
    assert result.iloc[3] == 3.0
    assert result.iloc[9] == 9.0



def test_ema_matches_pandas_ewm():
    series = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    expected = series.ewm(span=5, adjust=False, min_periods=5).mean()
    result = ema(series, 5)
    pd.testing.assert_series_equal(result, expected)


def test_rsi_ema():
    np.random.seed(42)
    prices = pd.Series(100 + np.cumsum(np.random.randn(50)))
    result = rsi_ema(prices, 14)
    
    assert len(result) == len(prices)
    assert all(0 <= v <= 100 or pd.isna(v) for v in result)
    assert not pd.isna(result.iloc[-1])


def test_vwap():
    df = pd.DataFrame({
        'high': [101, 102, 103, 104, 105],
        'low': [99, 100, 101, 102, 103],
        'close': [100, 101, 102, 103, 104],
        'volume': [1000, 1500, 2000, 1200, 1800]
    })
    
    result = vwap(df)
    
    assert len(result) == len(df)
    assert result.iloc[0] == 100.0
    assert result.iloc[-1] > result.iloc[0]


def test_vwap_zero_volume():
    df = pd.DataFrame({
        'high': [100, 100, 100],
        'low': [100, 100, 100],
        'close': [100, 100, 100],
        'volume': [0, 0, 0]
    })
    
    result = vwap(df)
    assert all(pd.isna(v) or v == 100.0 for v in result)


def test_atr_basic_behaviour():
    df = pd.DataFrame(
        {
            "open": [10, 11, 12, 13, 14, 15],
            "high": [11, 13, 13, 14, 15, 16],
            "low": [9, 10, 11, 12, 12, 13],
            "close": [10, 12, 12, 13, 14, 15],
            "volume": [100] * 6,
        }
    )
    result = atr(df, period=3)
    # First values should be NaN until min_periods satisfied
    assert result.iloc[0] != result.iloc[0]  # NaN check
    assert not pd.isna(result.iloc[2])  # first value available at period boundary
    assert result.iloc[-1] > 0
    # ATR should smooth true range; compare with manual ewm on TR
    true_range = (
        pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs(),
            ],
            axis=1,
        )
        .max(axis=1)
    )
    expected = true_range.ewm(alpha=1 / 3, adjust=False, min_periods=3).mean()
    assert abs(result.iloc[-1] - expected.iloc[-1]) < 1e-9
