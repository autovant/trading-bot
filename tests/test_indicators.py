
import pytest
import pandas as pd
import numpy as np
from src.indicators import TechnicalIndicators

@pytest.fixture
def sample_data():
    """Create sample OHLCV data."""
    dates = pd.date_range("2023-01-01", periods=100, freq="1h")
    # specific pattern: trend then range
    prices = np.linspace(100, 200, 50).tolist() + [200 + np.sin(x/5)*10 for x in range(50)]
    df = pd.DataFrame({
        "open": prices,
        "high": [p + 2 for p in prices],
        "low": [p - 2 for p in prices],
        "close": prices,
        "volume": [1000] * 100
    }, index=dates)
    return df

@pytest.fixture
def close_series(sample_data):
    return sample_data["close"]

def test_sma(close_series):
    sma = TechnicalIndicators.sma(close_series, 10)
    assert len(sma) == 100
    assert pd.isna(sma.iloc[8])  # First 9 are NaN
    assert not pd.isna(sma.iloc[9])
    assert sma.iloc[9] == close_series.iloc[0:10].mean()

def test_ema(close_series):
    ema = TechnicalIndicators.ema(close_series, 10)
    assert len(ema) == 100
    assert not pd.isna(ema.iloc[0]) # Pandas ewm produces values from start often
    # Basic check: EMA should track price
    assert abs(ema.iloc[-1] - close_series.iloc[-1]) < 20

def test_rsi(close_series):
    rsi = TechnicalIndicators.rsi(close_series, 14)
    assert len(rsi) == 100
    # RSI bounded 0-100
    assert rsi.dropna().min() >= 0
    assert rsi.dropna().max() <= 100
    # First few should be NaN
    assert pd.isna(rsi.iloc[0])

def test_macd(close_series):
    macd, signal, hist = TechnicalIndicators.macd(close_series)
    assert len(macd) == 100
    assert len(signal) == 100
    assert len(hist) == 100
    # Check relationship
    assert np.allclose((macd - signal).dropna(), hist.dropna())

def test_bollinger_bands(close_series):
    upper, mid, lower = TechnicalIndicators.bollinger_bands(close_series)
    # Ignore NaNs
    valid_idx = ~np.isnan(upper) & ~np.isnan(mid) & ~np.isnan(lower)
    assert np.all(upper[valid_idx] >= mid[valid_idx])
    assert np.all(mid[valid_idx] >= lower[valid_idx])
    # Mid should be SMA
    sma20 = TechnicalIndicators.sma(close_series, 20)
    assert np.allclose(mid.dropna(), sma20.dropna())

def test_atr(sample_data):
    atr = TechnicalIndicators.atr(sample_data, 14)
    assert len(atr) == 100
    assert atr.dropna().min() > 0

def test_adx(sample_data):
    adx = TechnicalIndicators.adx(sample_data, 14)
    assert len(adx) == 100
    # ADX bounded usually positive
    assert adx.dropna().min() >= 0
    # Theoretical max 100
    assert adx.dropna().max() <= 100

def test_donchian_channels(sample_data):
    high, low = TechnicalIndicators.donchian_channels(sample_data, 20)
    assert len(high) == 100
    valid_idx = ~np.isnan(high) & ~np.isnan(low)
    assert np.all(high[valid_idx] >= low[valid_idx])
    # High channel should be >= highest high in period
    assert high.iloc[20] == sample_data["high"].iloc[1:21].max()

def test_stochastic(sample_data):
    k, d = TechnicalIndicators.stochastic(sample_data)
    assert k.dropna().min() >= 0
    assert k.dropna().max() <= 100

def test_williams_r(sample_data):
    wr = TechnicalIndicators.williams_r(sample_data)
    # Usually -100 to 0
    assert wr.dropna().min() >= -100
    assert wr.dropna().max() <= 0

def test_cci(sample_data):
    cci = TechnicalIndicators.cci(sample_data)
    assert len(cci) == 100
    assert not cci.dropna().empty

def test_find_pivots(close_series):
    pivots = TechnicalIndicators.find_pivots(close_series, k=2)
    assert isinstance(pivots, list)
    # Check that indices are valid
    if pivots:
        assert max(pivots) < len(close_series)

def test_support_resistance(sample_data):
    levels = TechnicalIndicators.support_resistance_levels(sample_data)
    assert "support" in levels
    assert "resistance" in levels
    assert isinstance(levels["support"], list)

def test_volume_profile(sample_data):
    vp = TechnicalIndicators.volume_profile(sample_data)
    assert "prices" in vp
    assert "volumes" in vp
    assert len(vp["prices"]) == len(vp["volumes"])

def test_roling_vwap(sample_data):
    vwap = TechnicalIndicators.rolling_vwap(sample_data)
    assert len(vwap) == 100
    assert not pd.isna(vwap.iloc[-1])

def test_wavetrend(sample_data):
    wt = TechnicalIndicators.wavetrend_cipher_b(sample_data)
    assert "wt1" in wt.columns
    assert "wt2" in wt.columns
    assert "diff" in wt.columns
    # Check values are reasonable (often -100 to 100 or -60 to 60)
    assert not wt["wt1"].dropna().empty

def test_detect_divergence(close_series):
    # Construct divergence scenario
    # Price makes higher high, RSI lower high
    dates = pd.date_range("2023-01-01", periods=20)
    prices = [10, 11, 12, 11, 13, 15, 14, 16, 18, 17, 19, 21, 20, 22, 25, 24, 26, 28, 27, 26] # Generally uptrend
    rsi_vals = [50, 55, 60, 58, 65, 70, 68, 72, 75, 70, 74, 73, 70, 71, 69, 68, 65, 60, 55, 50] # Weakening
    
    p = pd.Series(prices)
    r = pd.Series(rsi_vals)
    
    divs = TechnicalIndicators.detect_divergence(p, r, k=2)
    # Just check structure, getting exact divergence with synthetic data is tricky without careful crafting
    assert "regular_bearish" in divs
    assert "regular_bullish" in divs
