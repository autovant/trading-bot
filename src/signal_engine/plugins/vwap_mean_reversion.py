"""
Bucket C: VWAP + Mean Reversion Plugin (0-25 points)

Analyzes price relative to VWAP and volume:
- VWAP calculation with standard deviation bands
- Distance to VWAP normalized scoring
- Volume z-score confirmation
- Mean reversion zone detection
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from src.signal_engine.plugins.base import PluginResult, ScoringPlugin
from src.signal_engine.schemas import StrategyProfile, VwapBias

logger = logging.getLogger(__name__)


class VwapMeanReversionPlugin(ScoringPlugin):
    """
    VWAP + Mean Reversion scoring plugin.
    
    Computes a 0-25 score based on:
    - Price position relative to VWAP (0-10 points)
    - Distance to VWAP bands (0-8 points)
    - Volume z-score confirmation (0-7 points)
    """
    
    name = "vwap_mean_reversion"
    max_score = 25
    
    # Default parameters
    VWAP_PERIOD = 20  # Rolling VWAP period
    BAND_STDEV = 2.0  # Standard deviations for bands
    VOLUME_ZSCORE_PERIOD = 20
    
    def compute(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
    ) -> PluginResult:
        """Compute VWAP + Mean Reversion score."""
        reasons = []
        metadata: Dict[str, Any] = {}
        score = 0
        
        min_periods = max(self.VWAP_PERIOD + 10, 50)
        if not self.validate_data(df, min_periods):
            return PluginResult(
                name=self.name,
                score=0,
                reasons=["Insufficient data for VWAP analysis"],
                metadata={"vwap_bias": VwapBias.AT.value},
            )
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        
        # Calculate VWAP and bands
        vwap = self._rolling_vwap(high, low, close, volume, self.VWAP_PERIOD)
        vwap_std = self._vwap_std(close, vwap, self.VWAP_PERIOD)
        
        vwap_val = self.safe_get(vwap)
        std_val = self.safe_get(vwap_std)
        upper_band = vwap_val + (self.BAND_STDEV * std_val)
        lower_band = vwap_val - (self.BAND_STDEV * std_val)
        
        current_close = self.safe_get(close)
        
        metadata["vwap"] = round(vwap_val, 2)
        metadata["vwap_upper"] = round(upper_band, 2)
        metadata["vwap_lower"] = round(lower_band, 2)
        
        # Calculate distance to VWAP as percentage
        if vwap_val > 0:
            vwap_distance_pct = (current_close - vwap_val) / vwap_val
        else:
            vwap_distance_pct = 0
        
        metadata["vwap_distance_pct"] = round(vwap_distance_pct, 4)
        
        # Price position relative to VWAP (0-10 points)
        vwap_score = 0
        
        if current_close > vwap_val:
            # Above VWAP - bullish bias
            if current_close < upper_band:
                # Healthy position above VWAP but not extended
                vwap_score = 10
                reasons.append("Price above VWAP (bullish)")
                vwap_bias = VwapBias.ABOVE
            else:
                # Extended above upper band - less bullish
                vwap_score = 5
                reasons.append("Price extended above VWAP upper band")
                vwap_bias = VwapBias.ABOVE
        elif current_close < vwap_val:
            # Below VWAP
            if current_close > lower_band:
                # Slight discount - potential mean reversion
                vwap_score = 6
                reasons.append("Price slightly below VWAP (discount zone)")
                vwap_bias = VwapBias.BELOW
            else:
                # Deep discount - strong mean reversion potential
                vwap_score = 8
                reasons.append("Price at lower VWAP band (mean reversion zone)")
                vwap_bias = VwapBias.BELOW
        else:
            vwap_score = 7
            reasons.append("Price at VWAP")
            vwap_bias = VwapBias.AT
        
        score += min(10, vwap_score)
        metadata["vwap_score"] = vwap_score
        metadata["vwap_bias"] = vwap_bias.value
        
        # Distance scoring (0-8 points) - reward being near VWAP or at bands
        distance_score = 0
        abs_distance = abs(vwap_distance_pct)
        
        if abs_distance < 0.005:
            # Very close to VWAP
            distance_score = 8
            reasons.append("At VWAP level")
        elif abs_distance < 0.01:
            distance_score = 6
        elif abs_distance < 0.02:
            distance_score = 4
        elif abs_distance < 0.03:
            distance_score = 2
        else:
            # Far from VWAP
            distance_score = 0
        
        # Bonus for being at bands with reversal potential
        if current_close <= lower_band:
            distance_score += 2
            metadata["mean_revert_zone"] = True
            reasons.append("At lower band - mean reversion zone")
        else:
            metadata["mean_revert_zone"] = False
        
        score += min(8, distance_score)
        metadata["distance_score"] = distance_score
        
        # Volume z-score confirmation (0-7 points)
        vol_zscore = self._volume_zscore(volume, self.VOLUME_ZSCORE_PERIOD)
        zscore_val = self.safe_get(vol_zscore)
        
        metadata["volume_zscore"] = round(zscore_val, 2)
        
        volume_score = 0
        min_vol_zscore = strategy.gates.volume_zscore_min
        
        if zscore_val > 1.5:
            # High volume - strong confirmation
            volume_score = 7
            reasons.append(f"High volume confirmation (z={zscore_val:.1f})")
        elif zscore_val > 0.5:
            volume_score = 5
            reasons.append(f"Above average volume (z={zscore_val:.1f})")
        elif zscore_val > min_vol_zscore:
            volume_score = 3
            reasons.append(f"Normal volume (z={zscore_val:.1f})")
        else:
            # Low volume - weak confirmation
            volume_score = 1
            reasons.append(f"Low volume (z={zscore_val:.1f})")
        
        score += min(7, volume_score)
        metadata["volume_score"] = volume_score
        
        return PluginResult(
            name=self.name,
            score=min(self.max_score, score),
            max_score=self.max_score,
            reasons=reasons,
            metadata=metadata,
        )
    
    def _rolling_vwap(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        volume: pd.Series,
        period: int,
    ) -> pd.Series:
        """Calculate rolling VWAP."""
        typical_price = (high + low + close) / 3
        vwap_num = (typical_price * volume).rolling(window=period).sum()
        vwap_den = volume.rolling(window=period).sum()
        return vwap_num / vwap_den.replace(0, 1)
    
    def _vwap_std(self, close: pd.Series, vwap: pd.Series, period: int) -> pd.Series:
        """Calculate standard deviation from VWAP."""
        deviation = (close - vwap) ** 2
        variance = deviation.rolling(window=period).mean()
        return np.sqrt(variance)
    
    def _volume_zscore(self, volume: pd.Series, period: int) -> pd.Series:
        """Calculate volume z-score."""
        vol_mean = volume.rolling(window=period).mean()
        vol_std = volume.rolling(window=period).std()
        return (volume - vol_mean) / vol_std.replace(0, 1)
