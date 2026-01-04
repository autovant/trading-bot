"""
Signal Engine for the Confluence Signal Engine.

Core signal generation logic with:
- BUY/SELL/HOLD decision rules
- Idempotency (no duplicate signals)
- Cooldown tracking
- Feature attachment for downstream consumers
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from src.signal_engine.scoring import ScoringEngine, ScoringResult
from src.signal_engine.schemas import (
    AlertPayload,
    CandleData,
    SignalOutput,
    SignalSide,
    SignalStrength,
    StrategyProfile,
)

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Core signal generation engine.
    
    Generates BUY/SELL/HOLD signals based on:
    - Confluence score from ScoringEngine
    - Strategy thresholds
    - Gate enforcement
    - Cooldown management
    - Idempotency tracking
    """
    
    def __init__(
        self,
        scoring_engine: Optional[ScoringEngine] = None,
        max_emitted_signals: int = 10000,
    ):
        """
        Initialize signal engine.
        
        Args:
            scoring_engine: Scoring engine instance. Defaults to new instance.
            max_emitted_signals: Max idempotency keys to track before pruning
        """
        self.scoring = scoring_engine or ScoringEngine()
        
        # Track emitted signal keys for idempotency
        self._emitted_keys: Set[str] = set()
        self._max_emitted = max_emitted_signals
        
        # Track last signal time per subscription for cooldown
        # Key: (exchange, symbol, timeframe) -> candles_since_signal
        self._last_signal_candles: Dict[tuple, int] = defaultdict(lambda: 100)
        
        # Track if data is degraded per subscription
        self._degraded_streams: Set[tuple] = set()
    
    def process_candle(
        self,
        df: pd.DataFrame,
        exchange: str,
        symbol: str,
        timeframe: str,
        strategy: StrategyProfile,
        candle: Optional[CandleData] = None,
        candle_closed: bool = True,
    ) -> Optional[SignalOutput]:
        """
        Process new candle data and generate signal.
        
        Args:
            df: OHLCV DataFrame with at least the required lookback
            exchange: Exchange name
            symbol: Trading symbol
            timeframe: Timeframe string (e.g., "1h")
            strategy: Strategy profile to use
            candle: Current candle data (for output)
            candle_closed: Whether candle is confirmed closed
            
        Returns:
            SignalOutput if a new signal should be emitted, None otherwise
        """
        sub_key = (exchange, symbol, timeframe)
        
        # Increment candles since last signal
        candles_since = self._last_signal_candles[sub_key]
        if candle_closed:
            self._last_signal_candles[sub_key] += 1
            candles_since = self._last_signal_candles[sub_key]
        
        # Check if data is degraded
        data_degraded = sub_key in self._degraded_streams
        
        # Run scoring
        scoring_result = self.scoring.compute(
            df=df,
            strategy=strategy,
            candle_closed=candle_closed,
            last_signal_candles_ago=candles_since,
            data_degraded=data_degraded,
        )
        
        # Determine signal side
        side = self._determine_side(scoring_result, strategy)
        
        # Build candle dict for output
        if candle:
            candle_dict = candle.to_dict()
            timestamp = candle.timestamp
        else:
            # Extract from DataFrame
            last = df.iloc[-1]
            candle_dict = {
                "o": float(last["open"]),
                "h": float(last["high"]),
                "l": float(last["low"]),
                "c": float(last["close"]),
                "v": float(last["volume"]),
            }
            timestamp = datetime.now(timezone.utc)
        
        # Compute idempotency key
        idempotency_key = SignalOutput.compute_idempotency_key(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            side=side,
            score=scoring_result.final_score,
        )
        
        # Check idempotency
        if idempotency_key in self._emitted_keys:
            logger.debug(f"Duplicate signal blocked: {idempotency_key}")
            return None
        
        # For HOLD signals, don't emit but also don't mark as emitted
        if side == SignalSide.HOLD:
            return None
        
        # Create signal output
        signal = SignalOutput(
            exchange=exchange,
            symbol=symbol,
            tf=timeframe,
            ts=timestamp,
            candle=candle_dict,
            score=scoring_result.final_score,
            side=side,
            strength=SignalOutput.classify_strength(scoring_result.final_score),
            reasons=scoring_result.reasons[:10],  # Limit to top 10 reasons
            gates=[g.to_dict() for g in scoring_result.gates],
            features=self._extract_key_features(scoring_result.features),
            bucket_scores=scoring_result.bucket_scores,
            penalties_applied=scoring_result.penalties,
            strategy_id=strategy.name,
            idempotency_key=idempotency_key,
        )
        
        # Track emission
        self._emitted_keys.add(idempotency_key)
        self._prune_emitted_keys()
        
        # Reset cooldown on signal
        if side in (SignalSide.BUY, SignalSide.SELL):
            self._last_signal_candles[sub_key] = 0
        
        logger.info(
            f"Signal generated: {exchange}/{symbol}/{timeframe} "
            f"side={side.value} score={scoring_result.final_score}"
        )
        
        return signal
    
    def _determine_side(
        self,
        result: ScoringResult,
        strategy: StrategyProfile,
    ) -> SignalSide:
        """
        Determine signal side based on score and gates.
        
        Rules:
        - BUY: score >= buy_threshold AND trend_bucket >= min_trend AND gates pass
        - SELL: score <= sell_threshold OR strong bearish confluence AND gates pass
        - HOLD: otherwise
        """
        # If any gate fails, always HOLD
        if not result.all_gates_passed:
            return SignalSide.HOLD
        
        score = result.final_score
        trend_score = result.bucket_scores.get("trend_regime", 0)
        
        # Check for BUY
        if score >= strategy.buy_threshold:
            if trend_score >= strategy.min_trend_score:
                return SignalSide.BUY
        
        # Check for SELL
        # Strong bearish: low score AND bearish trend indication
        if score <= strategy.sell_threshold:
            trend_result = result.bucket_results.get("trend_regime")
            if trend_result:
                regime = trend_result.metadata.get("regime", "chop")
                if regime == "bear" or score <= strategy.sell_threshold - 10:
                    return SignalSide.SELL
        
        return SignalSide.HOLD
    
    def _extract_key_features(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key features for signal output (minimal subset)."""
        key_features = {}
        
        # Include most important features
        important_keys = [
            "ema_50", "ema_200", "adx", "regime",
            "rsi", "macd_histogram", "osc_state",
            "vwap", "vwap_distance_pct", "volume_zscore",
            "nearest_support", "nearest_resistance",
        ]
        
        for key in important_keys:
            if key in features and features[key] is not None:
                key_features[key] = features[key]
        
        return key_features
    
    def _prune_emitted_keys(self) -> None:
        """Prune old emitted keys if limit exceeded."""
        if len(self._emitted_keys) > self._max_emitted:
            # Remove half of the oldest keys (approximate via set reduction)
            to_remove = len(self._emitted_keys) - (self._max_emitted // 2)
            for _ in range(to_remove):
                if self._emitted_keys:
                    self._emitted_keys.pop()
    
    def mark_data_degraded(self, exchange: str, symbol: str, timeframe: str) -> None:
        """Mark a subscription as having degraded data."""
        self._degraded_streams.add((exchange, symbol, timeframe))
        logger.warning(f"Data marked degraded: {exchange}/{symbol}/{timeframe}")
    
    def mark_data_healthy(self, exchange: str, symbol: str, timeframe: str) -> None:
        """Mark a subscription as having healthy data."""
        self._degraded_streams.discard((exchange, symbol, timeframe))
        logger.info(f"Data marked healthy: {exchange}/{symbol}/{timeframe}")
    
    def reset_cooldown(self, exchange: str, symbol: str, timeframe: str) -> None:
        """Reset cooldown for a subscription."""
        self._last_signal_candles[(exchange, symbol, timeframe)] = 100
    
    def get_cooldown_status(self, exchange: str, symbol: str, timeframe: str) -> int:
        """Get candles since last signal for a subscription."""
        return self._last_signal_candles[(exchange, symbol, timeframe)]
    
    def is_signal_duplicate(self, idempotency_key: str) -> bool:
        """Check if a signal with this key was already emitted."""
        return idempotency_key in self._emitted_keys


class SignalProcessor:
    """
    High-level signal processor that coordinates data + signal generation.
    
    This class can be used as the main entry point for processing market data
    and generating signals across multiple subscriptions.
    """
    
    def __init__(
        self,
        signal_engine: Optional[SignalEngine] = None,
    ):
        self.engine = signal_engine or SignalEngine()
        
        # Cache of OHLCV data per subscription
        self._data_cache: Dict[tuple, pd.DataFrame] = {}
        self._max_cache_size = 500  # Max candles to keep in memory
    
    def update_data(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        new_candles: pd.DataFrame,
    ) -> None:
        """
        Update cached data with new candles.
        
        Args:
            exchange: Exchange name
            symbol: Trading symbol
            timeframe: Timeframe string
            new_candles: DataFrame with new candle data
        """
        key = (exchange, symbol, timeframe)
        
        if key in self._data_cache:
            # Append new data
            existing = self._data_cache[key]
            combined = pd.concat([existing, new_candles], ignore_index=True)
            # Remove duplicates by timestamp
            if "timestamp" in combined.columns:
                combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
            # Trim to max size
            if len(combined) > self._max_cache_size:
                combined = combined.iloc[-self._max_cache_size:]
            self._data_cache[key] = combined
        else:
            # Initialize cache
            self._data_cache[key] = new_candles.iloc[-self._max_cache_size:]
    
    def get_cached_data(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
    ) -> Optional[pd.DataFrame]:
        """Get cached OHLCV data for a subscription."""
        return self._data_cache.get((exchange, symbol, timeframe))
    
    def process(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        strategy: StrategyProfile,
        candle: Optional[CandleData] = None,
        candle_closed: bool = True,
    ) -> Optional[SignalOutput]:
        """
        Process signal generation for a subscription.
        
        Args:
            exchange: Exchange name
            symbol: Trading symbol
            timeframe: Timeframe string
            strategy: Strategy profile
            candle: Current candle (optional)
            candle_closed: Whether candle is closed
            
        Returns:
            SignalOutput if signal generated, None otherwise
        """
        df = self.get_cached_data(exchange, symbol, timeframe)
        
        if df is None or len(df) < strategy.gates.min_candles:
            logger.warning(
                f"Insufficient data for {exchange}/{symbol}/{timeframe}: "
                f"{len(df) if df is not None else 0} candles"
            )
            return None
        
        return self.engine.process_candle(
            df=df,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            strategy=strategy,
            candle=candle,
            candle_closed=candle_closed,
        )
    
    def clear_cache(self, exchange: str, symbol: str, timeframe: str) -> None:
        """Clear cached data for a subscription."""
        key = (exchange, symbol, timeframe)
        if key in self._data_cache:
            del self._data_cache[key]
