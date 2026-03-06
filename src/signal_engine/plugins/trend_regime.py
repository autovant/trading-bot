"""
Bucket A: Trend Regime Plugin (0-25 points)

Analyzes trend strength and direction using:
- EMA(50) vs EMA(200) direction and crossover
- ADX(14) strength scoring  
- Price slope/ROC smoothing
- Regime classification (bull/bear/chop)
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from src.signal_engine.plugins.base import PluginResult, ScoringPlugin
from src.signal_engine.schemas import RegimeLabel, StrategyProfile

logger = logging.getLogger(__name__)


class TrendRegimePlugin(ScoringPlugin):
    """
    Trend Regime scoring plugin.
    
    Computes a 0-25 score based on:
    - EMA alignment and crossover (0-10 points)
    - ADX strength (0-10 points)
    - ROC/momentum confirmation (0-5 points)
    """
    
    name = "trend_regime"
    max_score = 25
    
    # Default indicator periods
    EMA_FAST = 50
    EMA_SLOW = 200
    ADX_PERIOD = 14
    ROC_PERIOD = 10
    
    def compute(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
    ) -> PluginResult:
        """Compute trend regime score."""
        reasons = []
        metadata: Dict[str, Any] = {}
        score = 0
        
        # Validate data
        min_periods = max(self.EMA_SLOW + 10, strategy.gates.min_candles)
        if not self.validate_data(df, min_periods):
            return PluginResult(
                name=self.name,
                score=0,
                reasons=["Insufficient data for trend analysis"],
                metadata={"regime": RegimeLabel.CHOP.value, "data_valid": False},
            )
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        
        # Calculate EMAs
        ema_fast = self._ema(close, self.EMA_FAST)
        ema_slow = self._ema(close, self.EMA_SLOW)
        
        ema_fast_val = self.safe_get(ema_fast)
        ema_slow_val = self.safe_get(ema_slow)
        current_close = self.safe_get(close)
        
        metadata["ema_50"] = round(ema_fast_val, 2)
        metadata["ema_200"] = round(ema_slow_val, 2)
        
        # EMA alignment scoring (0-10 points)
        ema_score = 0
        if ema_fast_val > ema_slow_val:
            # Bullish alignment
            ema_score += 5
            reasons.append("EMA 50 > EMA 200 (bullish alignment)")
            
            # Price above both EMAs
            if current_close > ema_fast_val:
                ema_score += 3
                reasons.append("Price above EMA 50")
            if current_close > ema_slow_val:
                ema_score += 2
                reasons.append("Price above EMA 200")
        else:
            # Bearish alignment - add for short signals
            if current_close < ema_fast_val and current_close < ema_slow_val:
                ema_score += 2  # Bearish confirmation helps on sell side
                reasons.append("Price below both EMAs (bearish)")
        
        # Check for recent crossover
        if len(ema_fast) >= 5:
            prev_fast = self.safe_get(ema_fast, -5)
            prev_slow = self.safe_get(ema_slow, -5)
            
            if prev_fast <= prev_slow and ema_fast_val > ema_slow_val:
                ema_score = min(10, ema_score + 3)
                reasons.append("Recent bullish EMA crossover")
            elif prev_fast >= prev_slow and ema_fast_val < ema_slow_val:
                ema_score = max(0, ema_score - 2)
                reasons.append("Recent bearish EMA crossover")
        
        score += min(10, ema_score)
        metadata["ema_score"] = ema_score
        
        # ADX scoring (0-10 points)
        adx = self._adx(high, low, close, self.ADX_PERIOD)
        plus_di = self._plus_di(high, low, close, self.ADX_PERIOD)
        minus_di = self._minus_di(high, low, close, self.ADX_PERIOD)
        
        adx_val = self.safe_get(adx)
        plus_di_val = self.safe_get(plus_di)
        minus_di_val = self.safe_get(minus_di)
        
        metadata["adx"] = round(adx_val, 2)
        metadata["plus_di"] = round(plus_di_val, 2)
        metadata["minus_di"] = round(minus_di_val, 2)
        
        adx_score = 0
        if adx_val >= 40:
            adx_score = 10
            reasons.append(f"Strong trend (ADX={adx_val:.1f})")
        elif adx_val >= 25:
            adx_score = 7
            reasons.append(f"Moderate trend (ADX={adx_val:.1f})")
        elif adx_val >= 20:
            adx_score = 4
            reasons.append(f"Weak trend (ADX={adx_val:.1f})")
        else:
            adx_score = 0
            reasons.append(f"No trend/chop (ADX={adx_val:.1f})")
        
        # DI crossover bonus
        if plus_di_val > minus_di_val and ema_fast_val > ema_slow_val:
            adx_score = min(10, adx_score + 2)
            reasons.append("+DI > -DI confirms bullish")
        
        score += min(10, adx_score)
        metadata["adx_score"] = adx_score
        
        # ROC/Momentum scoring (0-5 points)
        roc = self._roc(close, self.ROC_PERIOD)
        roc_val = self.safe_get(roc)
        
        metadata["roc"] = round(roc_val, 4)
        
        roc_score = 0
        if roc_val > 0.02:  # >2% momentum
            roc_score = 5
            reasons.append(f"Strong positive momentum (ROC={roc_val:.2%})")
        elif roc_val > 0.01:
            roc_score = 3
            reasons.append(f"Positive momentum (ROC={roc_val:.2%})")
        elif roc_val > 0:
            roc_score = 1
            reasons.append("Slight positive momentum")
        elif roc_val < -0.02:
            roc_score = 0
            reasons.append(f"Negative momentum (ROC={roc_val:.2%})")
        
        score += min(5, roc_score)
        metadata["roc_score"] = roc_score
        
        # Determine regime label
        if score >= 15 and ema_fast_val > ema_slow_val:
            regime = RegimeLabel.BULL
        elif score <= 8 or (ema_fast_val < ema_slow_val and adx_val >= 20):
            regime = RegimeLabel.BEAR
        else:
            regime = RegimeLabel.CHOP
        
        metadata["regime"] = regime.value
        metadata["data_valid"] = True
        
        return PluginResult(
            name=self.name,
            score=min(self.max_score, score),
            max_score=self.max_score,
            reasons=reasons,
            metadata=metadata,
        )
    
    def _ema(self, data: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average."""
        return data.ewm(span=period, adjust=False).mean()
    
    def _roc(self, data: pd.Series, period: int) -> pd.Series:
        """Calculate Rate of Change."""
        return data.pct_change(periods=period)
    
    def _true_range(self, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """Calculate True Range."""
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    def _adx(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """Calculate Average Directional Index."""
        tr = self._true_range(high, low, close)
        atr = tr.ewm(span=period, adjust=False).mean()
        
        up_move = high.diff()
        down_move = -low.diff()
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        plus_dm = pd.Series(plus_dm, index=high.index)
        minus_dm = pd.Series(minus_dm, index=high.index)
        
        plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
        
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.ewm(span=period, adjust=False).mean()
        
        return adx
    
    def _plus_di(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """Calculate +DI."""
        tr = self._true_range(high, low, close)
        atr = tr.ewm(span=period, adjust=False).mean()
        
        up_move = high.diff()
        down_move = -low.diff()
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        plus_dm = pd.Series(plus_dm, index=high.index)
        
        return 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    
    def _minus_di(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """Calculate -DI."""
        tr = self._true_range(high, low, close)
        atr = tr.ewm(span=period, adjust=False).mean()
        
        up_move = high.diff()
        down_move = -low.diff()
        
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        minus_dm = pd.Series(minus_dm, index=high.index)
        
        return 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
