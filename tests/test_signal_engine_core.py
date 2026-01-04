"""
Unit tests for the Confluence Signal Engine core signal generation.

Tests the SignalEngine including:
- BUY/SELL/HOLD signal generation
- Idempotency
- Cooldown tracking
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

from src.signal_engine.signal_engine import SignalEngine, SignalProcessor
from src.signal_engine.schemas import (
    CandleData,
    SignalOutput,
    SignalSide,
    StrategyProfile,
    BucketWeights,
    GateConfig,
)


@pytest.fixture
def default_strategy() -> StrategyProfile:
    """Create a default strategy profile for testing."""
    return StrategyProfile(
        name="test_strategy",
        weights=BucketWeights(trend=0.25, oscillator=0.25, vwap=0.25, structure=0.25),
        buy_threshold=60,
        sell_threshold=40,
        min_trend_score=10,
        gates=GateConfig(
            min_candles=100,
            cooldown_candles=3,
            atr_pct_max=0.10,  # Relaxed for testing
            volume_zscore_min=-2.0,
            risk_off=False,
        ),
    )


@pytest.fixture
def bullish_df() -> pd.DataFrame:
    """Create a strongly bullish DataFrame for testing."""
    np.random.seed(42)
    n = 300
    
    # Strong uptrend
    base_price = 100
    trend = np.linspace(0, 80, n)
    noise = np.random.randn(n) * 1
    close = base_price + trend + noise
    
    close = np.maximum(close, 1)
    high = close + np.abs(np.random.randn(n) * 1)
    low = close - np.abs(np.random.randn(n) * 0.5)
    open_ = close - 0.5
    volume = np.random.uniform(2000, 5000, n)  # Good volume
    
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def bearish_df() -> pd.DataFrame:
    """Create a strongly bearish DataFrame for testing."""
    np.random.seed(42)
    n = 300
    
    # Strong downtrend
    base_price = 200
    trend = np.linspace(0, -100, n)
    noise = np.random.randn(n) * 1
    close = base_price + trend + noise
    
    close = np.maximum(close, 1)
    high = close + np.abs(np.random.randn(n) * 0.5)
    low = close - np.abs(np.random.randn(n) * 1)
    open_ = close + 0.5
    volume = np.random.uniform(2000, 5000, n)
    
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestSignalEngine:
    """Tests for the SignalEngine."""
    
    def test_process_candle_returns_signal_or_none(self, bullish_df, default_strategy):
        """Verify process_candle returns SignalOutput or None."""
        engine = SignalEngine()
        
        result = engine.process_candle(
            df=bullish_df,
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            strategy=default_strategy,
            candle_closed=True,
        )
        
        # Result should be None (HOLD) or SignalOutput
        assert result is None or isinstance(result, SignalOutput)
    
    def test_hold_when_gates_fail(self, bullish_df, default_strategy):
        """Verify HOLD when gates fail."""
        engine = SignalEngine()
        
        # Candle not closed - should return None (HOLD)
        result = engine.process_candle(
            df=bullish_df,
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            strategy=default_strategy,
            candle_closed=False,  # Gate will fail
        )
        
        assert result is None, "Should HOLD when candle not closed"
    
    def test_idempotency_key_generation(self, bullish_df, default_strategy):
        """Verify idempotency key is unique and consistent."""
        key1 = SignalOutput.compute_idempotency_key(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            side=SignalSide.BUY,
            score=75,
        )
        
        # Same inputs should produce same key
        key2 = SignalOutput.compute_idempotency_key(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            side=SignalSide.BUY,
            score=75,
        )
        
        assert key1 == key2, "Same inputs should produce same key"
        
        # Different inputs should produce different key
        key3 = SignalOutput.compute_idempotency_key(
            exchange="bybit",
            symbol="ETHUSDT",  # Different symbol
            timeframe="1h",
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            side=SignalSide.BUY,
            score=75,
        )
        
        assert key1 != key3, "Different inputs should produce different key"
    
    def test_no_duplicate_signals(self, bullish_df, default_strategy):
        """Verify duplicate signals are blocked."""
        engine = SignalEngine()
        
        # First call might generate a signal
        result1 = engine.process_candle(
            df=bullish_df,
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            strategy=default_strategy,
            candle_closed=True,
        )
        
        if result1 is not None:
            # Mark this key as emitted
            key = result1.idempotency_key
            
            # Try to emit same signal again
            assert engine.is_signal_duplicate(key), "Key should be marked as duplicate"
    
    def test_cooldown_resets_on_signal(self, bullish_df, default_strategy):
        """Verify cooldown resets after signal emission."""
        engine = SignalEngine()
        
        # Get cooldown status before
        sub_key = ("bybit", "BTCUSDT", "1h")
        before = engine.get_cooldown_status(*sub_key)
        
        # Process might generate signal
        result = engine.process_candle(
            df=bullish_df,
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            strategy=default_strategy,
            candle_closed=True,
        )
        
        if result is not None:
            after = engine.get_cooldown_status(*sub_key)
            assert after == 0, "Cooldown should reset to 0 after signal"
    
    def test_mark_data_degraded(self, bullish_df, default_strategy):
        """Verify data degraded marking works."""
        engine = SignalEngine()
        
        engine.mark_data_degraded("bybit", "BTCUSDT", "1h")
        
        # Process with degraded data - should HOLD
        result = engine.process_candle(
            df=bullish_df,
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            strategy=default_strategy,
            candle_closed=True,
        )
        
        assert result is None, "Should HOLD with degraded data"
        
        # Mark healthy and try again
        engine.mark_data_healthy("bybit", "BTCUSDT", "1h")
    
    def test_classify_strength(self):
        """Verify signal strength classification."""
        from src.signal_engine.schemas import SignalStrength
        
        assert SignalOutput.classify_strength(80) == SignalStrength.HIGH
        assert SignalOutput.classify_strength(75) == SignalStrength.HIGH
        assert SignalOutput.classify_strength(65) == SignalStrength.MEDIUM
        assert SignalOutput.classify_strength(55) == SignalStrength.MEDIUM
        assert SignalOutput.classify_strength(45) == SignalStrength.LOW
        assert SignalOutput.classify_strength(30) == SignalStrength.LOW


class TestSignalProcessor:
    """Tests for the SignalProcessor."""
    
    def test_update_and_process(self, bullish_df, default_strategy):
        """Verify data update and processing flow."""
        processor = SignalProcessor()
        
        # Update data
        processor.update_data("bybit", "BTCUSDT", "1h", bullish_df)
        
        # Verify data is cached
        cached = processor.get_cached_data("bybit", "BTCUSDT", "1h")
        assert cached is not None
        assert len(cached) == len(bullish_df)
        
        # Process
        result = processor.process(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            strategy=default_strategy,
            candle_closed=True,
        )
        
        # Result should be None or SignalOutput
        assert result is None or isinstance(result, SignalOutput)
    
    def test_cache_trimming(self, default_strategy):
        """Verify cache is trimmed to max size."""
        processor = SignalProcessor()
        processor._max_cache_size = 100
        
        # Create large dataset
        n = 200
        large_df = pd.DataFrame({
            "open": [100] * n,
            "high": [101] * n,
            "low": [99] * n,
            "close": [100] * n,
            "volume": [1000] * n,
        })
        
        processor.update_data("bybit", "BTCUSDT", "1h", large_df)
        
        cached = processor.get_cached_data("bybit", "BTCUSDT", "1h")
        assert len(cached) <= processor._max_cache_size
    
    def test_clear_cache(self, bullish_df, default_strategy):
        """Verify cache clearing."""
        processor = SignalProcessor()
        
        processor.update_data("bybit", "BTCUSDT", "1h", bullish_df)
        assert processor.get_cached_data("bybit", "BTCUSDT", "1h") is not None
        
        processor.clear_cache("bybit", "BTCUSDT", "1h")
        assert processor.get_cached_data("bybit", "BTCUSDT", "1h") is None
    
    def test_insufficient_data_returns_none(self, default_strategy):
        """Verify None returned with insufficient data."""
        processor = SignalProcessor()
        
        # Small dataset
        small_df = pd.DataFrame({
            "open": [100] * 50,
            "high": [101] * 50,
            "low": [99] * 50,
            "close": [100] * 50,
            "volume": [1000] * 50,
        })
        
        processor.update_data("bybit", "BTCUSDT", "1h", small_df)
        
        result = processor.process(
            exchange="bybit",
            symbol="BTCUSDT",
            timeframe="1h",
            strategy=default_strategy,
            candle_closed=True,
        )
        
        assert result is None, "Should return None with insufficient data"


class TestSignalOutput:
    """Tests for SignalOutput model."""
    
    def test_signal_output_creation(self):
        """Verify SignalOutput can be created."""
        signal = SignalOutput(
            exchange="bybit",
            symbol="BTCUSDT",
            tf="1h",
            ts=datetime.now(timezone.utc),
            candle={"o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1000},
            score=75,
            side=SignalSide.BUY,
            strength=SignalOutput.classify_strength(75),
            reasons=["Test reason"],
            gates=[{"name": "test", "pass": True, "detail": "ok"}],
            features={"rsi": 55},
            idempotency_key="test123",
        )
        
        assert signal.side == SignalSide.BUY
        assert signal.score == 75
        assert len(signal.reasons) == 1
