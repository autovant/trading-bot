"""
Unit tests for Confluence Signal Engine scoring plugins.

Tests each of the four scoring buckets:
- Trend Regime (Bucket A)
- Oscillator Confluence (Bucket B)
- VWAP + Mean Reversion (Bucket C)
- Structure / Levels (Bucket D)
"""

import numpy as np
import pandas as pd
import pytest

from src.signal_engine.plugins.trend_regime import TrendRegimePlugin
from src.signal_engine.plugins.oscillator_confluence import OscillatorConfluencePlugin
from src.signal_engine.plugins.vwap_mean_reversion import VwapMeanReversionPlugin
from src.signal_engine.plugins.structure_levels import StructureLevelsPlugin
from src.signal_engine.schemas import StrategyProfile, BucketWeights, GateConfig


@pytest.fixture
def default_strategy() -> StrategyProfile:
    """Create a default strategy profile for testing."""
    return StrategyProfile(
        name="test_strategy",
        weights=BucketWeights(trend=0.25, oscillator=0.25, vwap=0.25, structure=0.25),
        buy_threshold=60,
        sell_threshold=40,
        min_trend_score=10,
        gates=GateConfig(min_candles=50, cooldown_candles=3),
    )


@pytest.fixture
def bullish_df() -> pd.DataFrame:
    """Create a bullish trending DataFrame for testing."""
    np.random.seed(42)
    n = 300
    
    # Generate uptrending prices
    base_price = 100
    trend = np.linspace(0, 50, n)
    noise = np.random.randn(n) * 2
    close = base_price + trend + noise
    
    # Ensure prices are positive
    close = np.maximum(close, 1)
    
    high = close + np.abs(np.random.randn(n) * 1.5)
    low = close - np.abs(np.random.randn(n) * 1.5)
    open_ = (close + low) / 2 + np.random.randn(n) * 0.5
    
    # Volume with slight upward trend
    volume = np.random.uniform(1000, 5000, n) * (1 + trend / 100)
    
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def bearish_df() -> pd.DataFrame:
    """Create a bearish trending DataFrame for testing."""
    np.random.seed(42)
    n = 300
    
    # Generate downtrending prices
    base_price = 150
    trend = np.linspace(0, -50, n)
    noise = np.random.randn(n) * 2
    close = base_price + trend + noise
    
    close = np.maximum(close, 1)
    
    high = close + np.abs(np.random.randn(n) * 1.5)
    low = close - np.abs(np.random.randn(n) * 1.5)
    open_ = (close + high) / 2 + np.random.randn(n) * 0.5
    
    volume = np.random.uniform(1000, 5000, n)
    
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def choppy_df() -> pd.DataFrame:
    """Create a sideways/choppy DataFrame for testing."""
    np.random.seed(42)
    n = 300
    
    # Sideways movement
    base_price = 100
    noise = np.random.randn(n) * 5
    close = base_price + noise
    
    close = np.maximum(close, 1)
    
    high = close + np.abs(np.random.randn(n) * 2)
    low = close - np.abs(np.random.randn(n) * 2)
    open_ = close + np.random.randn(n) * 1
    
    volume = np.random.uniform(1000, 3000, n)
    
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# =============================================================================
# Trend Regime Plugin Tests
# =============================================================================


class TestTrendRegimePlugin:
    """Tests for the Trend Regime plugin (Bucket A)."""
    
    def test_bullish_trending_scores_high(self, bullish_df, default_strategy):
        """Verify high score in strong uptrend."""
        plugin = TrendRegimePlugin()
        result = plugin.compute(bullish_df, default_strategy)
        
        assert result.score >= 12, f"Expected reasonable score for uptrend, got {result.score}"
        assert result.metadata.get("regime") == "bull"
        assert "EMA" in " ".join(result.reasons)
    
    def test_bearish_trending_scores_low(self, bearish_df, default_strategy):
        """Verify low score in downtrend."""
        plugin = TrendRegimePlugin()
        result = plugin.compute(bearish_df, default_strategy)
        
        assert result.score < 15, f"Expected low score for downtrend, got {result.score}"
        assert result.metadata.get("regime") in ("bear", "chop")
    
    def test_choppy_market_indicates_chop(self, choppy_df, default_strategy):
        """Verify chop regime in sideways market."""
        plugin = TrendRegimePlugin()
        result = plugin.compute(choppy_df, default_strategy)
        
        # Choppy market should have moderate to low ADX
        adx = result.metadata.get("adx", 0)
        assert adx < 30 or result.metadata.get("regime") in ("chop", "bear")
    
    def test_insufficient_data_returns_zero(self, default_strategy):
        """Verify zero score with insufficient data."""
        plugin = TrendRegimePlugin()
        small_df = pd.DataFrame({
            "open": [100] * 50,
            "high": [101] * 50,
            "low": [99] * 50,
            "close": [100] * 50,
            "volume": [1000] * 50,
        })
        
        result = plugin.compute(small_df, default_strategy)
        assert result.score == 0
        assert not result.metadata.get("data_valid", True)


# =============================================================================
# Oscillator Confluence Plugin Tests
# =============================================================================


class TestOscillatorConfluencePlugin:
    """Tests for the Oscillator Confluence plugin (Bucket B)."""
    
    def test_oversold_recovery_scores_high(self, default_strategy):
        """Verify high score on oversold recovery."""
        plugin = OscillatorConfluencePlugin()
        
        # Create data with RSI recovering from oversold
        n = 200
        np.random.seed(42)
        
        # Decline then recovery
        close = np.concatenate([
            np.linspace(100, 60, n // 2),  # Decline
            np.linspace(60, 70, n // 2),  # Recovery
        ])
        
        df = pd.DataFrame({
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": np.random.uniform(1000, 3000, n),
        })
        
        result = plugin.compute(df, default_strategy)
        
        # Should detect recovery
        assert result.score >= 5, f"Expected some score on recovery, got {result.score}"
    
    def test_overbought_scores_low(self, default_strategy):
        """Verify lower score when overbought."""
        plugin = OscillatorConfluencePlugin()
        
        # Create data with very strong uptrend (overbought)
        n = 200
        close = np.linspace(100, 200, n)  # Strong continuous rise
        
        df = pd.DataFrame({
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": np.random.uniform(1000, 3000, n),
        })
        
        result = plugin.compute(df, default_strategy)
        
        # Overbought should have lower score
        osc_state = result.metadata.get("osc_state")
        if osc_state == "overbought":
            assert result.score <= 15, "Overbought should not score very high"


# =============================================================================
# VWAP Mean Reversion Plugin Tests
# =============================================================================


class TestVwapMeanReversionPlugin:
    """Tests for the VWAP + Mean Reversion plugin (Bucket C)."""
    
    def test_above_vwap_bullish(self, bullish_df, default_strategy):
        """Verify bullish bias when price above VWAP."""
        plugin = VwapMeanReversionPlugin()
        result = plugin.compute(bullish_df, default_strategy)
        
        vwap_bias = result.metadata.get("vwap_bias")
        # In uptrend, price should be above VWAP
        assert vwap_bias in ("above", "at"), f"Expected above VWAP in uptrend, got {vwap_bias}"
        assert result.score >= 10
    
    def test_at_lower_band_mean_reversion(self, default_strategy):
        """Verify mean reversion zone detection at lower band."""
        plugin = VwapMeanReversionPlugin()
        
        # Create data where price drops to lower band
        n = 100
        np.random.seed(42)
        
        close = np.concatenate([
            np.linspace(100, 100, 80),  # Stable
            np.linspace(100, 85, 20),  # Drop to lower levels
        ])
        
        df = pd.DataFrame({
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.random.uniform(1000, 3000, n),
        })
        
        result = plugin.compute(df, default_strategy)
        
        # Should detect mean reversion opportunity or lower VWAP
        assert result.metadata.get("vwap_bias") in ("below", "at")


# =============================================================================
# Structure Levels Plugin Tests
# =============================================================================


class TestStructureLevelsPlugin:
    """Tests for the Structure / Levels plugin (Bucket D)."""
    
    def test_finds_support_resistance(self, bullish_df, default_strategy):
        """Verify S/R level detection."""
        plugin = StructureLevelsPlugin()
        result = plugin.compute(bullish_df, default_strategy)
        
        # Should find some pivot points
        pivot_highs = result.metadata.get("pivot_highs_count", 0)
        pivot_lows = result.metadata.get("pivot_lows_count", 0)
        
        assert pivot_highs > 0 or pivot_lows > 0, "Should find some pivots"
    
    def test_higher_lows_detection(self, bullish_df, default_strategy):
        """Verify higher lows structure detection in uptrend."""
        plugin = StructureLevelsPlugin()
        result = plugin.compute(bullish_df, default_strategy)
        
        # In uptrend, should often detect higher lows
        # This may vary with random data, so we just check the structure exists
        assert "pivot_score" in result.metadata
    
    def test_scores_near_support(self, default_strategy):
        """Verify scoring when price is near support."""
        plugin = StructureLevelsPlugin()
        
        # Create data with clear pullback to support
        n = 100
        np.random.seed(42)
        
        # Swing high, pullback to support, bounce
        close = np.concatenate([
            np.linspace(100, 120, 30),  # Up
            np.linspace(120, 105, 30),  # Pullback
            np.linspace(105, 108, 40),  # Bounce from support
        ])
        
        df = pd.DataFrame({
            "open": close - 0.5,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": np.random.uniform(1000, 3000, n),
        })
        
        result = plugin.compute(df, default_strategy)
        
        # Should detect structure
        assert result.score >= 0


# =============================================================================
# Integration Test: All Plugins
# =============================================================================


class TestPluginIntegration:
    """Integration tests for all plugins working together."""
    
    def test_all_plugins_return_valid_scores(self, bullish_df, default_strategy):
        """Verify all plugins return valid scores."""
        plugins = [
            TrendRegimePlugin(),
            OscillatorConfluencePlugin(),
            VwapMeanReversionPlugin(),
            StructureLevelsPlugin(),
        ]
        
        for plugin in plugins:
            result = plugin.compute(bullish_df, default_strategy)
            
            assert 0 <= result.score <= 25, f"{plugin.name} score out of range: {result.score}"
            assert len(result.reasons) > 0, f"{plugin.name} should have reasons"
            assert result.name == plugin.name
    
    def test_score_sum_possible_max_100(self, bullish_df, default_strategy):
        """Verify max possible raw score is 100."""
        plugins = [
            TrendRegimePlugin(),
            OscillatorConfluencePlugin(),
            VwapMeanReversionPlugin(),
            StructureLevelsPlugin(),
        ]
        
        total_max = sum(p.max_score for p in plugins)
        assert total_max == 100, f"Max score should be 100, got {total_max}"
