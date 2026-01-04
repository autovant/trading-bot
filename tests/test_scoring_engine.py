"""
Unit tests for the Confluence Signal Engine scoring engine.

Tests the ScoringEngine aggregator including:
- Weighted score combination
- Penalty application
- Gate checking
"""

import numpy as np
import pandas as pd
import pytest

from src.signal_engine.scoring import ScoringEngine, ScoringResult
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
        gates=GateConfig(
            min_candles=100,
            cooldown_candles=3,
            atr_pct_max=0.05,
            volume_zscore_min=-1.0,
            risk_off=False,
        ),
    )


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Create sample OHLCV data for testing."""
    np.random.seed(42)
    n = 250
    
    base_price = 100
    trend = np.linspace(0, 20, n)
    noise = np.random.randn(n) * 2
    close = base_price + trend + noise
    
    close = np.maximum(close, 1)
    high = close + np.abs(np.random.randn(n) * 1.5)
    low = close - np.abs(np.random.randn(n) * 1.5)
    open_ = (close + low) / 2 + np.random.randn(n) * 0.5
    volume = np.random.uniform(1000, 5000, n)
    
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestScoringEngine:
    """Tests for the ScoringEngine."""
    
    def test_compute_returns_scoring_result(self, sample_df, default_strategy):
        """Verify compute returns a ScoringResult."""
        engine = ScoringEngine()
        result = engine.compute(sample_df, default_strategy)
        
        assert isinstance(result, ScoringResult)
        assert 0 <= result.final_score <= 100
        assert result.bucket_scores is not None
        assert len(result.bucket_scores) == 4
    
    def test_weighted_score_calculation(self, sample_df, default_strategy):
        """Verify weighted score calculation."""
        engine = ScoringEngine()
        result = engine.compute(sample_df, default_strategy)
        
        # Calculate expected weighted score
        weights = default_strategy.weights
        expected = 0
        for plugin_name, score in result.bucket_scores.items():
            weight_key = engine._plugin_weight_map.get(plugin_name, "trend")
            weight = getattr(weights, weight_key, 0.25)
            expected += (score / 25.0) * 100 * weight
        
        # Raw score should match (before penalties)
        assert abs(result.raw_score - int(round(expected))) <= 1
    
    def test_penalty_high_atr(self, default_strategy):
        """Verify ATR penalty is applied."""
        # Create high volatility data
        n = 250
        np.random.seed(42)
        
        base_price = 100
        # High volatility swings
        close = base_price + np.random.randn(n) * 20
        close = np.maximum(close, 1)
        
        high = close + np.abs(np.random.randn(n) * 10)
        low = close - np.abs(np.random.randn(n) * 10)
        open_ = close + np.random.randn(n) * 5
        volume = np.random.uniform(1000, 5000, n)
        
        df = pd.DataFrame({
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
        
        engine = ScoringEngine()
        result = engine.compute(df, default_strategy)
        
        # Check if ATR penalty was considered
        atr_pct = engine._compute_atr_pct(df)
        if atr_pct > default_strategy.gates.atr_pct_max:
            assert result.penalty_points > 0, "High ATR should apply penalty"
            assert any("volatility" in p.lower() or "atr" in p.lower() for p in result.penalties)
    
    def test_penalty_low_volume(self, default_strategy):
        """Verify low volume penalty is applied."""
        n = 250
        np.random.seed(42)
        
        close = np.linspace(100, 120, n)
        high = close + 1
        low = close - 1
        open_ = close - 0.5
        
        # Very low volume at the end
        volume = np.concatenate([
            np.random.uniform(1000, 3000, n - 20),
            np.random.uniform(10, 50, 20),  # Very low volume
        ])
        
        df = pd.DataFrame({
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
        
        # Lower the volume z-score threshold
        strategy = StrategyProfile(
            name="test",
            gates=GateConfig(volume_zscore_min=-0.5),  # Stricter threshold
        )
        
        engine = ScoringEngine()
        result = engine.compute(df, strategy)
        
        vol_zscore = engine._compute_volume_zscore(df)
        if vol_zscore < strategy.gates.volume_zscore_min:
            assert result.penalty_points > 0, "Low volume should apply penalty"
    
    def test_gate_data_sufficiency_pass(self, sample_df, default_strategy):
        """Verify data sufficiency gate passes with enough data."""
        engine = ScoringEngine()
        result = engine.compute(sample_df, default_strategy)
        
        data_gate = next(
            (g for g in result.gates if g.name == "data_sufficiency"),
            None
        )
        
        assert data_gate is not None
        assert data_gate.passed, f"Should pass with {len(sample_df)} candles"
    
    def test_gate_data_sufficiency_fail(self, default_strategy):
        """Verify data sufficiency gate fails with insufficient data."""
        # Create small dataset
        small_df = pd.DataFrame({
            "open": [100] * 50,
            "high": [101] * 50,
            "low": [99] * 50,
            "close": [100] * 50,
            "volume": [1000] * 50,
        })
        
        engine = ScoringEngine()
        result = engine.compute(small_df, default_strategy)
        
        data_gate = next(
            (g for g in result.gates if g.name == "data_sufficiency"),
            None
        )
        
        assert data_gate is not None
        assert not data_gate.passed, "Should fail with only 50 candles (min 100)"
        assert not result.all_gates_passed
    
    def test_gate_candle_close(self, sample_df, default_strategy):
        """Verify candle close gate."""
        engine = ScoringEngine()
        
        # Test with candle closed
        result_closed = engine.compute(sample_df, default_strategy, candle_closed=True)
        close_gate = next(g for g in result_closed.gates if g.name == "candle_close_only")
        assert close_gate.passed
        
        # Test with candle open
        result_open = engine.compute(sample_df, default_strategy, candle_closed=False)
        close_gate = next(g for g in result_open.gates if g.name == "candle_close_only")
        assert not close_gate.passed
    
    def test_gate_cooldown_active(self, sample_df, default_strategy):
        """Verify cooldown gate when recently signaled."""
        engine = ScoringEngine()
        
        # Cooldown is 3, signal was 2 candles ago - should block
        result = engine.compute(sample_df, default_strategy, last_signal_candles_ago=2)
        
        cooldown_gate = next(g for g in result.gates if g.name == "cooldown")
        assert not cooldown_gate.passed, "Should be in cooldown"
    
    def test_gate_cooldown_passed(self, sample_df, default_strategy):
        """Verify cooldown gate when cooldown expired."""
        engine = ScoringEngine()
        
        # Cooldown is 3, signal was 10 candles ago - should pass
        result = engine.compute(sample_df, default_strategy, last_signal_candles_ago=10)
        
        cooldown_gate = next(g for g in result.gates if g.name == "cooldown")
        assert cooldown_gate.passed, "Cooldown should have expired"
    
    def test_gate_degraded_data(self, sample_df, default_strategy):
        """Verify degraded data gate."""
        engine = ScoringEngine()
        
        # Test with healthy data
        result_healthy = engine.compute(sample_df, default_strategy, data_degraded=False)
        deg_gate = next(g for g in result_healthy.gates if g.name == "degraded_data")
        assert deg_gate.passed
        
        # Test with degraded data
        result_degraded = engine.compute(sample_df, default_strategy, data_degraded=True)
        deg_gate = next(g for g in result_degraded.gates if g.name == "degraded_data")
        assert not deg_gate.passed
    
    def test_gate_risk_off(self, sample_df):
        """Verify risk off gate."""
        engine = ScoringEngine()
        
        # Strategy with risk_off = True
        strategy_off = StrategyProfile(
            name="risk_off_test",
            gates=GateConfig(risk_off=True),
        )
        
        result = engine.compute(sample_df, strategy_off)
        
        risk_gate = next(g for g in result.gates if g.name == "risk_off")
        assert not risk_gate.passed, "Risk off should block signals"
    
    def test_all_gates_passed_flag(self, sample_df, default_strategy):
        """Verify all_gates_passed flag is correct."""
        engine = ScoringEngine()
        
        # All gates should pass with default conditions
        result = engine.compute(
            sample_df,
            default_strategy,
            candle_closed=True,
            last_signal_candles_ago=100,
            data_degraded=False,
        )
        
        # Check individual gates match the flag
        individual_pass = all(g.passed for g in result.gates)
        assert result.all_gates_passed == individual_pass
    
    def test_reasons_accumulated(self, sample_df, default_strategy):
        """Verify reasons are accumulated from all plugins."""
        engine = ScoringEngine()
        result = engine.compute(sample_df, default_strategy)
        
        assert len(result.reasons) > 0, "Should have reasons from plugins"
    
    def test_features_accumulated(self, sample_df, default_strategy):
        """Verify features are accumulated from all plugins."""
        engine = ScoringEngine()
        result = engine.compute(sample_df, default_strategy)
        
        # Should have features from multiple plugins
        assert "ema_50" in result.features or "rsi" in result.features
        assert len(result.features) > 5, "Should have multiple features"
