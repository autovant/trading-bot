"""
Bucket D: Structure / Levels Plugin (0-25 points)

Analyzes market structure and key levels:
- Pivot highs/lows detection
- Support/Resistance level identification
- Distance to nearest S/R
- Break and retest pattern detection
- Optional HTF confirmation
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.signal_engine.plugins.base import PluginResult, ScoringPlugin
from src.signal_engine.schemas import StrategyProfile

logger = logging.getLogger(__name__)


class StructureLevelsPlugin(ScoringPlugin):
    """
    Structure / Levels scoring plugin.
    
    Computes a 0-25 score based on:
    - Distance to nearest support/resistance (0-10 points)
    - Pivot point detection (0-8 points)
    - Break and retest patterns (0-7 points)
    """
    
    name = "structure_levels"
    max_score = 25
    
    # Default parameters
    PIVOT_LOOKBACK = 5  # Candles to look back for pivots
    SR_TOLERANCE = 0.01  # 1% tolerance for clustering levels
    MIN_TOUCHES = 2  # Minimum touches to confirm a level
    RETEST_TOLERANCE = 0.005  # 0.5% tolerance for retest detection
    
    def compute(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
    ) -> PluginResult:
        """Compute structure/levels score."""
        reasons = []
        metadata: Dict[str, Any] = {}
        score = 0
        
        min_periods = max(50, self.PIVOT_LOOKBACK * 10)
        if not self.validate_data(df, min_periods):
            return PluginResult(
                name=self.name,
                score=0,
                reasons=["Insufficient data for structure analysis"],
                metadata={},
            )
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        current_close = self.safe_get(close)
        current_high = self.safe_get(high)
        current_low = self.safe_get(low)
        
        # Find pivot points
        pivot_highs, pivot_lows = self._find_pivots(high, low, self.PIVOT_LOOKBACK)
        
        metadata["pivot_highs_count"] = len(pivot_highs)
        metadata["pivot_lows_count"] = len(pivot_lows)
        
        # Identify S/R levels by clustering pivots
        resistance_levels = self._cluster_levels([p[1] for p in pivot_highs], self.SR_TOLERANCE)
        support_levels = self._cluster_levels([p[1] for p in pivot_lows], self.SR_TOLERANCE)
        
        metadata["resistance_levels"] = [round(r, 2) for r in resistance_levels[:5]]
        metadata["support_levels"] = [round(s, 2) for s in support_levels[:5]]
        
        # Find nearest support and resistance
        nearest_support = self._find_nearest_level(current_close, support_levels, below=True)
        nearest_resistance = self._find_nearest_level(current_close, resistance_levels, below=False)
        
        metadata["nearest_support"] = round(nearest_support, 2) if nearest_support else None
        metadata["nearest_resistance"] = round(nearest_resistance, 2) if nearest_resistance else None
        
        # Distance to S/R scoring (0-10 points)
        sr_score = 0
        
        if nearest_support and current_close > 0:
            support_distance_pct = (current_close - nearest_support) / current_close
            metadata["distance_to_support_pct"] = round(support_distance_pct, 4)
            
            if support_distance_pct < 0.01:
                # Very close to support - bullish
                sr_score += 7
                reasons.append(f"At support level ({support_distance_pct:.2%} away)")
            elif support_distance_pct < 0.02:
                sr_score += 5
                reasons.append(f"Near support ({support_distance_pct:.2%} away)")
            elif support_distance_pct < 0.05:
                sr_score += 3
        
        if nearest_resistance and current_close > 0:
            resistance_distance_pct = (nearest_resistance - current_close) / current_close
            metadata["distance_to_resistance_pct"] = round(resistance_distance_pct, 4)
            
            if resistance_distance_pct > 0.05:
                # Good room to resistance - bullish
                sr_score += 3
                reasons.append(f"Good room to resistance ({resistance_distance_pct:.2%})")
            elif resistance_distance_pct < 0.01:
                # At resistance - less bullish
                sr_score -= 2
                reasons.append(f"At resistance level ({resistance_distance_pct:.2%} away)")
        
        score += max(0, min(10, sr_score))
        metadata["sr_score"] = max(0, min(10, sr_score))
        
        # Pivot scoring (0-8 points)
        pivot_score = 0
        
        # Check if recent candle is a pivot
        recent_pivot_high = self._is_recent_pivot_high(high, self.PIVOT_LOOKBACK)
        recent_pivot_low = self._is_recent_pivot_low(low, self.PIVOT_LOOKBACK)
        
        metadata["recent_pivot_high"] = recent_pivot_high
        metadata["recent_pivot_low"] = recent_pivot_low
        
        if recent_pivot_low:
            # Just made a higher low - bullish
            pivot_score += 5
            reasons.append("Recent pivot low formed")
        
        # Check for higher highs / higher lows structure
        if len(pivot_lows) >= 2:
            last_two_lows = sorted(pivot_lows[-4:], key=lambda x: x[0])[-2:]
            if len(last_two_lows) >= 2 and last_two_lows[1][1] > last_two_lows[0][1]:
                pivot_score += 3
                reasons.append("Higher lows structure")
                metadata["higher_lows"] = True
            else:
                metadata["higher_lows"] = False
        
        score += min(8, pivot_score)
        metadata["pivot_score"] = min(8, pivot_score)
        
        # Break and retest detection (0-7 points)
        retest_score = 0
        
        # Check for break and retest of resistance turned support
        retest_detected, retest_level = self._detect_retest(
            df, resistance_levels, support_levels, self.RETEST_TOLERANCE
        )
        
        if retest_detected:
            retest_score += 7
            reasons.append(f"Break and retest pattern at {retest_level:.2f}")
            metadata["retest_level"] = round(retest_level, 2)
            metadata["retest_detected"] = True
        else:
            metadata["retest_detected"] = False
        
        # Bonus for price above previous resistance
        if resistance_levels and current_close > max(resistance_levels):
            retest_score += 2
            reasons.append("Price above all recent resistance")
        
        score += min(7, retest_score)
        metadata["retest_score"] = min(7, retest_score)
        
        return PluginResult(
            name=self.name,
            score=min(self.max_score, score),
            max_score=self.max_score,
            reasons=reasons,
            metadata=metadata,
        )
    
    def _find_pivots(
        self, high: pd.Series, low: pd.Series, lookback: int
    ) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        """Find pivot highs and lows."""
        pivot_highs = []
        pivot_lows = []
        
        for i in range(lookback, len(high) - lookback):
            # Pivot high: higher than surrounding candles
            if high.iloc[i] == high.iloc[i - lookback : i + lookback + 1].max():
                pivot_highs.append((i, high.iloc[i]))
            
            # Pivot low: lower than surrounding candles
            if low.iloc[i] == low.iloc[i - lookback : i + lookback + 1].min():
                pivot_lows.append((i, low.iloc[i]))
        
        return pivot_highs, pivot_lows
    
    def _cluster_levels(self, levels: List[float], tolerance: float) -> List[float]:
        """Cluster nearby price levels together."""
        if not levels:
            return []
        
        sorted_levels = sorted(levels)
        clusters = []
        current_cluster = [sorted_levels[0]]
        
        for level in sorted_levels[1:]:
            # Check if level is within tolerance of cluster mean
            cluster_mean = sum(current_cluster) / len(current_cluster)
            if abs(level - cluster_mean) / cluster_mean <= tolerance:
                current_cluster.append(level)
            else:
                # Start new cluster
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [level]
        
        # Add last cluster
        if current_cluster:
            clusters.append(sum(current_cluster) / len(current_cluster))
        
        return clusters
    
    def _find_nearest_level(
        self, price: float, levels: List[float], below: bool
    ) -> float | None:
        """Find nearest level above or below current price."""
        if not levels:
            return None
        
        if below:
            below_levels = [l for l in levels if l < price]
            return max(below_levels) if below_levels else None
        else:
            above_levels = [l for l in levels if l > price]
            return min(above_levels) if above_levels else None
    
    def _is_recent_pivot_high(self, high: pd.Series, lookback: int) -> bool:
        """Check if a recent candle is a pivot high."""
        if len(high) < lookback * 2 + 1:
            return False
        
        # Check the candle at position -lookback-1
        check_idx = -lookback - 1
        try:
            check_val = high.iloc[check_idx]
            surrounding = high.iloc[check_idx - lookback : check_idx + lookback + 1]
            return check_val == surrounding.max()
        except (IndexError, KeyError):
            return False
    
    def _is_recent_pivot_low(self, low: pd.Series, lookback: int) -> bool:
        """Check if a recent candle is a pivot low."""
        if len(low) < lookback * 2 + 1:
            return False
        
        check_idx = -lookback - 1
        try:
            check_val = low.iloc[check_idx]
            surrounding = low.iloc[check_idx - lookback : check_idx + lookback + 1]
            return check_val == surrounding.min()
        except (IndexError, KeyError):
            return False
    
    def _detect_retest(
        self,
        df: pd.DataFrame,
        resistance_levels: List[float],
        support_levels: List[float],
        tolerance: float,
    ) -> Tuple[bool, float]:
        """
        Detect break and retest pattern.
        
        Looks for:
        1. Price broke above a resistance level
        2. Price pulled back to retest that level (now support)
        3. Price is now bouncing off
        """
        if len(df) < 20 or not resistance_levels:
            return False, 0.0
        
        current_close = df["close"].iloc[-1]
        current_low = df["low"].iloc[-1]
        
        for level in resistance_levels:
            # Check if current price is above the level
            if current_close > level * (1 + tolerance):
                # Check if recent low tested the level
                recent_lows = df["low"].iloc[-10:]
                touches = sum(
                    1 for low in recent_lows
                    if abs(low - level) / level <= tolerance
                )
                
                if touches >= 1:
                    # Break and retest confirmed
                    return True, level
        
        return False, 0.0
