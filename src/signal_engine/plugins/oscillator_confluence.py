"""
Bucket B: Oscillator Confluence Plugin (0-25 points)

Analyzes momentum and oscillator indicators:
- RSI(14) zone scoring
- Stochastic RSI crossover detection
- MACD histogram + slope analysis
- MFI(14) confirmation
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from src.signal_engine.plugins.base import PluginResult, ScoringPlugin
from src.signal_engine.schemas import OscillatorState, StrategyProfile

logger = logging.getLogger(__name__)


class OscillatorConfluencePlugin(ScoringPlugin):
    """
    Oscillator Confluence scoring plugin.
    
    Computes a 0-25 score based on:
    - RSI zone and direction (0-7 points)
    - Stochastic RSI state (0-6 points)
    - MACD histogram + slope (0-7 points)
    - MFI confirmation (0-5 points)
    """
    
    name = "oscillator_confluence"
    max_score = 25
    
    # Default indicator periods
    RSI_PERIOD = 14
    STOCH_RSI_PERIOD = 14
    STOCH_RSI_K = 3
    STOCH_RSI_D = 3
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    MFI_PERIOD = 14
    
    def compute(
        self,
        df: pd.DataFrame,
        strategy: StrategyProfile,
    ) -> PluginResult:
        """Compute oscillator confluence score."""
        reasons = []
        metadata: Dict[str, Any] = {}
        score = 0
        
        min_periods = max(self.MACD_SLOW + self.MACD_SIGNAL + 10, 50)
        if not self.validate_data(df, min_periods):
            return PluginResult(
                name=self.name,
                score=0,
                reasons=["Insufficient data for oscillator analysis"],
                metadata={"osc_state": OscillatorState.NEUTRAL.value},
            )
        
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        
        # RSI scoring (0-7 points)
        rsi = self._rsi(close, self.RSI_PERIOD)
        rsi_val = self.safe_get(rsi)
        rsi_prev = self.safe_get(rsi, -2)
        
        metadata["rsi"] = round(rsi_val, 2)
        
        rsi_score = 0
        turning_up = rsi_val > rsi_prev
        
        if 30 <= rsi_val <= 50 and turning_up:
            # Ideal bullish zone - oversold recovery
            rsi_score = 7
            reasons.append(f"RSI recovering from oversold ({rsi_val:.1f})")
        elif 40 <= rsi_val <= 60:
            # Neutral zone with momentum
            rsi_score = 4 if turning_up else 2
            reasons.append(f"RSI neutral zone ({rsi_val:.1f})")
        elif rsi_val < 30:
            # Extremely oversold - contrarian bullish
            rsi_score = 5 if turning_up else 3
            reasons.append(f"RSI oversold ({rsi_val:.1f})")
        elif rsi_val > 70:
            # Overbought - reduce score
            rsi_score = 1
            reasons.append(f"RSI overbought ({rsi_val:.1f})")
        else:
            rsi_score = 3
        
        score += min(7, rsi_score)
        metadata["rsi_score"] = rsi_score
        metadata["turning_up"] = turning_up
        
        # Stochastic RSI scoring (0-6 points)
        stoch_k, stoch_d = self._stoch_rsi(close, self.STOCH_RSI_PERIOD, self.STOCH_RSI_K, self.STOCH_RSI_D)
        stoch_k_val = self.safe_get(stoch_k)
        stoch_d_val = self.safe_get(stoch_d)
        stoch_k_prev = self.safe_get(stoch_k, -2)
        stoch_d_prev = self.safe_get(stoch_d, -2)
        
        metadata["stoch_rsi_k"] = round(stoch_k_val, 2)
        metadata["stoch_rsi_d"] = round(stoch_d_val, 2)
        
        stoch_score = 0
        
        # Bullish crossover
        if stoch_k_prev <= stoch_d_prev and stoch_k_val > stoch_d_val:
            stoch_score = 6
            reasons.append("Stoch RSI bullish crossover")
        elif stoch_k_val > stoch_d_val:
            stoch_score = 4
            reasons.append("Stoch RSI %K > %D")
        elif stoch_k_val < 20:
            # Oversold zone
            stoch_score = 3 if stoch_k_val > stoch_k_prev else 2
            reasons.append(f"Stoch RSI oversold ({stoch_k_val:.1f})")
        elif stoch_k_val > 80:
            stoch_score = 1
            reasons.append(f"Stoch RSI overbought ({stoch_k_val:.1f})")
        else:
            stoch_score = 2
        
        score += min(6, stoch_score)
        metadata["stoch_score"] = stoch_score
        
        # MACD scoring (0-7 points)
        macd_line, signal_line, histogram = self._macd(
            close, self.MACD_FAST, self.MACD_SLOW, self.MACD_SIGNAL
        )
        
        macd_val = self.safe_get(macd_line)
        signal_val = self.safe_get(signal_line)
        hist_val = self.safe_get(histogram)
        hist_prev = self.safe_get(histogram, -2)
        hist_slope = hist_val - hist_prev
        
        metadata["macd"] = round(macd_val, 4)
        metadata["macd_signal"] = round(signal_val, 4)
        metadata["macd_histogram"] = round(hist_val, 4)
        metadata["macd_histogram_slope"] = round(hist_slope, 6)
        
        macd_score = 0
        
        # MACD line above signal
        if macd_val > signal_val:
            macd_score += 3
            reasons.append("MACD above signal line")
        
        # Histogram positive and growing
        if hist_val > 0:
            macd_score += 2
            if hist_slope > 0:
                macd_score += 2
                reasons.append("MACD histogram positive and growing")
            else:
                reasons.append("MACD histogram positive")
        elif hist_slope > 0:
            # Histogram negative but improving
            macd_score += 1
            reasons.append("MACD histogram improving")
        
        score += min(7, macd_score)
        metadata["macd_score"] = macd_score
        
        # MFI scoring (0-5 points)
        mfi = self._mfi(high, low, close, volume, self.MFI_PERIOD)
        mfi_val = self.safe_get(mfi)
        mfi_prev = self.safe_get(mfi, -2)
        
        metadata["mfi"] = round(mfi_val, 2)
        
        mfi_score = 0
        
        if 20 <= mfi_val <= 50 and mfi_val > mfi_prev:
            # Ideal money flow recovery
            mfi_score = 5
            reasons.append(f"MFI recovering ({mfi_val:.1f})")
        elif 40 <= mfi_val <= 60:
            mfi_score = 3
            reasons.append(f"MFI neutral ({mfi_val:.1f})")
        elif mfi_val < 20:
            mfi_score = 4 if mfi_val > mfi_prev else 2
            reasons.append(f"MFI oversold ({mfi_val:.1f})")
        elif mfi_val > 80:
            mfi_score = 1
            reasons.append(f"MFI overbought ({mfi_val:.1f})")
        else:
            mfi_score = 2
        
        score += min(5, mfi_score)
        metadata["mfi_score"] = mfi_score
        
        # Determine overall oscillator state
        if rsi_val < 30 or stoch_k_val < 20 or mfi_val < 20:
            osc_state = OscillatorState.OVERSOLD
        elif rsi_val > 70 or stoch_k_val > 80 or mfi_val > 80:
            osc_state = OscillatorState.OVERBOUGHT
        else:
            osc_state = OscillatorState.NEUTRAL
        
        metadata["osc_state"] = osc_state.value
        
        return PluginResult(
            name=self.name,
            score=min(self.max_score, score),
            max_score=self.max_score,
            reasons=reasons,
            metadata=metadata,
        )
    
    def _rsi(self, close: pd.Series, period: int) -> pd.Series:
        """Calculate Relative Strength Index."""
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        
        rs = avg_gain / avg_loss.replace(0, np.inf)
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _stoch_rsi(
        self, close: pd.Series, rsi_period: int, k_period: int, d_period: int
    ) -> tuple[pd.Series, pd.Series]:
        """Calculate Stochastic RSI."""
        rsi = self._rsi(close, rsi_period)
        
        rsi_min = rsi.rolling(window=rsi_period).min()
        rsi_max = rsi.rolling(window=rsi_period).max()
        
        stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, 1)
        stoch_rsi = stoch_rsi * 100
        
        k = stoch_rsi.rolling(window=k_period).mean()
        d = k.rolling(window=d_period).mean()
        
        return k, d
    
    def _macd(
        self, close: pd.Series, fast: int, slow: int, signal: int
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD (line, signal, histogram)."""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _mfi(
        self, high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int
    ) -> pd.Series:
        """Calculate Money Flow Index."""
        typical_price = (high + low + close) / 3
        raw_money_flow = typical_price * volume
        
        tp_change = typical_price.diff()
        
        positive_flow = raw_money_flow.where(tp_change > 0, 0)
        negative_flow = raw_money_flow.where(tp_change < 0, 0)
        
        positive_mf = positive_flow.rolling(window=period).sum()
        negative_mf = negative_flow.rolling(window=period).sum()
        
        mfi = 100 - (100 / (1 + positive_mf / negative_mf.replace(0, 1)))
        return mfi
