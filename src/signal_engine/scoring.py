"""
Scoring Engine for the Confluence Signal Engine.

Aggregates plugin scores with:
- Weighted bucket combination
- Penalty application (ATR, volume, bucket conflicts)
- Hard gate enforcement
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from src.signal_engine.plugins.base import PluginResult, ScoringPlugin
from src.signal_engine.plugins.trend_regime import TrendRegimePlugin
from src.signal_engine.plugins.oscillator_confluence import OscillatorConfluencePlugin
from src.signal_engine.plugins.vwap_mean_reversion import VwapMeanReversionPlugin
from src.signal_engine.plugins.structure_levels import StructureLevelsPlugin
from src.signal_engine.schemas import (
    FeatureSet,
    GateResult,
    RegimeLabel,
    SignalSide,
    StrategyProfile,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoringResult:
    """Complete scoring result from all plugins."""
    
    raw_score: int  # Sum of bucket scores before penalties
    final_score: int  # Score after penalties (0-100)
    bucket_scores: Dict[str, int]
    bucket_results: Dict[str, PluginResult]
    penalties: List[str]
    penalty_points: int
    gates: List[GateResult]
    all_gates_passed: bool
    features: Dict[str, Any]
    reasons: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_score": self.raw_score,
            "final_score": self.final_score,
            "bucket_scores": self.bucket_scores,
            "penalties": self.penalties,
            "penalty_points": self.penalty_points,
            "gates": [g.to_dict() for g in self.gates],
            "all_gates_passed": self.all_gates_passed,
            "reasons": self.reasons,
        }


class ScoringEngine:
    """
    Aggregates scores from all plugins with penalties and gates.
    
    Bucket weights are applied from the strategy profile.
    Penalties subtract up to 30 points for unfavorable conditions.
    Gates must all pass for a valid signal.
    """
    
    MAX_PENALTY = 30
    
    def __init__(
        self,
        plugins: Optional[List[ScoringPlugin]] = None,
    ):
        """
        Initialize scoring engine with plugins.
        
        Args:
            plugins: List of scoring plugins. Defaults to all four buckets.
        """
        self.plugins = plugins or [
            TrendRegimePlugin(),
            OscillatorConfluencePlugin(),
            VwapMeanReversionPlugin(),
            StructureLevelsPlugin(),
        ]
        
        # Map plugin names to their order for weighting
        self._plugin_weight_map = {
            "trend_regime": "trend",
            "oscillator_confluence": "oscillator",
            "vwap_mean_reversion": "vwap",
            "structure_levels": "structure",
        }
    
    def compute(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
        candle_closed: bool = True,
        last_signal_candles_ago: int = 100,
        data_degraded: bool = False,
    ) -> ScoringResult:
        """
        Compute complete score from all plugins.
        
        Args:
            df: OHLCV DataFrame
            strategy: Strategy profile with weights and gates
            candle_closed: Whether the current candle is confirmed closed
            last_signal_candles_ago: Candles since last signal (for cooldown)
            data_degraded: Whether data stream is in degraded state
            
        Returns:
            ScoringResult with scores, penalties, gates, and features
        """
        bucket_scores: Dict[str, int] = {}
        bucket_results: Dict[str, PluginResult] = {}
        all_reasons: List[str] = []
        all_features: Dict[str, Any] = {}
        
        # Run all plugins
        for plugin in self.plugins:
            try:
                result = plugin.compute(df, strategy)
                bucket_results[plugin.name] = result
                bucket_scores[plugin.name] = result.score
                all_reasons.extend(result.reasons)
                all_features.update(result.metadata)
            except Exception as e:
                logger.error(f"Plugin {plugin.name} failed: {e}")
                bucket_results[plugin.name] = PluginResult(
                    name=plugin.name,
                    score=0,
                    reasons=[f"Plugin error: {str(e)}"],
                )
                bucket_scores[plugin.name] = 0
        
        # Apply weights to get weighted scores
        weights = strategy.weights
        weighted_score = 0.0
        
        for plugin_name, raw_score in bucket_scores.items():
            weight_key = self._plugin_weight_map.get(plugin_name, "trend")
            weight = getattr(weights, weight_key, 0.25)
            # Normalize: each bucket is 0-25, weight sums to 1, final is 0-100
            weighted_score += (raw_score / 25.0) * 100 * weight
        
        raw_score = int(round(weighted_score))
        
        # Apply penalties
        penalties, penalty_points = self._compute_penalties(
            df, strategy, bucket_results
        )
        
        final_score = max(0, min(100, raw_score - penalty_points))
        
        # Check gates
        gates = self._check_gates(
            df,
            strategy,
            candle_closed=candle_closed,
            last_signal_candles_ago=last_signal_candles_ago,
            data_degraded=data_degraded,
        )
        
        all_gates_passed = all(g.passed for g in gates)
        
        return ScoringResult(
            raw_score=raw_score,
            final_score=final_score,
            bucket_scores=bucket_scores,
            bucket_results=bucket_results,
            penalties=penalties,
            penalty_points=penalty_points,
            gates=gates,
            all_gates_passed=all_gates_passed,
            features=all_features,
            reasons=all_reasons,
        )
    
    def _compute_penalties(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
        bucket_results: Dict[str, PluginResult],
    ) -> tuple[List[str], int]:
        """
        Compute penalty points.
        
        Penalties:
        - ATR% too high: -10
        - Low volume regime: -10
        - Bucket conflict (trend vs oscillators disagree): -10
        """
        penalties = []
        total_penalty = 0
        
        if len(df) < 14:
            return penalties, total_penalty
        
        # ATR% penalty
        atr_pct = self._compute_atr_pct(df)
        if atr_pct > strategy.gates.atr_pct_max:
            penalty = 10
            penalties.append(f"High volatility (ATR%={atr_pct:.2%}): -{penalty}")
            total_penalty += penalty
        
        # Low volume penalty
        vol_zscore = self._compute_volume_zscore(df)
        if vol_zscore < strategy.gates.volume_zscore_min:
            penalty = 10
            penalties.append(f"Low volume (z-score={vol_zscore:.2f}): -{penalty}")
            total_penalty += penalty
        
        # Bucket conflict penalty
        trend_result = bucket_results.get("trend_regime")
        osc_result = bucket_results.get("oscillator_confluence")
        
        if trend_result and osc_result:
            trend_regime = trend_result.metadata.get("regime", "chop")
            osc_state = osc_result.metadata.get("osc_state", "neutral")
            
            # Conflict: bullish trend but overbought oscillators, or vice versa
            if trend_regime == "bull" and osc_state == "overbought":
                penalty = 5
                penalties.append(f"Bucket conflict (bullish trend + overbought): -{penalty}")
                total_penalty += penalty
            elif trend_regime == "bear" and osc_state == "oversold":
                penalty = 5
                penalties.append(f"Bucket conflict (bearish trend + oversold): -{penalty}")
                total_penalty += penalty
        
        return penalties, min(total_penalty, self.MAX_PENALTY)
    
    def _check_gates(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
        candle_closed: bool,
        last_signal_candles_ago: int,
        data_degraded: bool,
    ) -> List[GateResult]:
        """Check all hard gates."""
        gates = []
        
        # Data sufficiency gate
        min_candles = strategy.gates.min_candles
        has_enough_data = len(df) >= min_candles
        gates.append(GateResult(
            name="data_sufficiency",
            passed=has_enough_data,
            detail=f"{len(df)}/{min_candles} candles",
        ))
        
        # Candle close gate
        gates.append(GateResult(
            name="candle_close_only",
            passed=candle_closed,
            detail="Candle closed" if candle_closed else "Candle still open",
        ))
        
        # Cooldown gate
        cooldown = strategy.gates.cooldown_candles
        cooldown_passed = last_signal_candles_ago >= cooldown
        gates.append(GateResult(
            name="cooldown",
            passed=cooldown_passed,
            detail=f"{last_signal_candles_ago}/{cooldown} candles since last signal",
        ))
        
        # Degraded data gate
        gates.append(GateResult(
            name="degraded_data",
            passed=not data_degraded,
            detail="Data stream healthy" if not data_degraded else "Data gaps detected",
        ))
        
        # Risk off gate
        gates.append(GateResult(
            name="risk_off",
            passed=not strategy.gates.risk_off,
            detail="Trading enabled" if not strategy.gates.risk_off else "Risk off mode",
        ))
        
        return gates
    
    def _compute_atr_pct(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute ATR as percentage of price."""
        if len(df) < period:
            return 0.0
        
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean().iloc[-1]
        current_price = close.iloc[-1]
        
        if current_price > 0:
            return atr / current_price
        return 0.0
    
    def _compute_volume_zscore(self, df: pd.DataFrame, period: int = 20) -> float:
        """Compute current volume z-score."""
        if len(df) < period:
            return 0.0
        
        volume = df["volume"]
        vol_mean = volume.rolling(window=period).mean().iloc[-1]
        vol_std = volume.rolling(window=period).std().iloc[-1]
        current_vol = volume.iloc[-1]
        
        if vol_std > 0:
            return (current_vol - vol_mean) / vol_std
        return 0.0
