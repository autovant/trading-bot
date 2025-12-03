"""
Technical analysis indicators with vectorized calculations.
"""

import numpy as np
import pandas as pd
from typing import Tuple, List
from scipy.signal import argrelextrema
import logging

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """Technical analysis indicators collection."""

    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return data.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(data: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return data.rolling(window=period).mean()

    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index."""
        delta = data.diff().astype(float)
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def macd(
        data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD (Moving Average Convergence Divergence)."""
        ema_fast = TechnicalIndicators.ema(data, fast)
        ema_slow = TechnicalIndicators.ema(data, slow)

        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.ema(macd_line, signal)
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(
        data: pd.Series, period: int = 20, std_dev: float = 2.0
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands."""
        sma = TechnicalIndicators.sma(data, period)
        std = data.rolling(window=period).std()

        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)

        return upper_band, sma, lower_band

    @staticmethod
    def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()

        return atr

    @staticmethod
    def adx(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average Directional Index."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # Calculate directional movement
        plus_dm = high.diff().astype(float)
        minus_dm = low.diff().astype(float)

        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        minus_dm = abs(minus_dm)

        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Smoothed averages
        atr = true_range.rolling(window=period).mean()
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

        # ADX calculation
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()

        return adx

    @staticmethod
    def donchian_channels(
        data: pd.DataFrame, period: int = 20
    ) -> Tuple[pd.Series, pd.Series]:
        """Donchian Channels."""
        high_channel = data["high"].rolling(window=period).max()
        low_channel = data["low"].rolling(window=period).min()

        return high_channel, low_channel

    @staticmethod
    def stochastic(
        data: pd.DataFrame, k_period: int = 14, d_period: int = 3
    ) -> Tuple[pd.Series, pd.Series]:
        """Stochastic Oscillator."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()

        k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
        d_percent = k_percent.rolling(window=d_period).mean()

        return k_percent, d_percent

    @staticmethod
    def williams_r(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """Williams %R."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()

        williams_r = -100 * ((highest_high - close) / (highest_high - lowest_low))

        return williams_r

    @staticmethod
    def cci(data: pd.DataFrame, period: int = 20) -> pd.Series:
        """Commodity Channel Index."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        typical_price = (high + low + close) / 3
        sma_tp = typical_price.rolling(window=period).mean()
        mean_deviation = typical_price.rolling(window=period).apply(
            lambda x: np.mean(np.abs(x - np.mean(x)))
        )

        cci = (typical_price - sma_tp) / (0.015 * mean_deviation)

        return cci

    @staticmethod
    def find_pivots(data: pd.Series, k: int = 3) -> List[int]:
        """Find pivot points (local extrema) in data."""
        try:
            # Find local maxima
            maxima_indices = argrelextrema(data.to_numpy(), np.greater, order=k)[0]

            # Find local minima
            minima_indices = argrelextrema(data.to_numpy(), np.less, order=k)[0]

            # Combine and sort
            pivot_indices = np.concatenate([maxima_indices, minima_indices])
            pivot_indices = np.sort(pivot_indices)

            return pivot_indices.tolist()

        except Exception as e:
            logger.error(f"Error finding pivots: {e}")
            return []

    @staticmethod
    def detect_divergence(
        price_data: pd.Series, indicator_data: pd.Series, k: int = 3
    ) -> dict:
        """Detect regular and hidden bullish/bearish divergences."""
        try:
            # Find pivots
            price_pivots_max = argrelextrema(price_data.to_numpy(), np.greater, order=k)[0]
            price_pivots_min = argrelextrema(price_data.to_numpy(), np.less, order=k)[0]
            
            ind_pivots_max = argrelextrema(indicator_data.to_numpy(), np.greater, order=k)[0]
            ind_pivots_min = argrelextrema(indicator_data.to_numpy(), np.less, order=k)[0]

            # Initialize results
            results = {
                "regular_bullish": False,
                "regular_bearish": False,
                "hidden_bullish": False,
                "hidden_bearish": False
            }

            # Need at least 2 pivots to compare
            if len(price_pivots_min) >= 2 and len(ind_pivots_min) >= 2:
                # Check Minima (Bullish Divergences)
                # We look at the last two minima
                p_min_curr = price_data.iloc[price_pivots_min[-1]]
                p_min_prev = price_data.iloc[price_pivots_min[-2]]
                
                i_min_curr = indicator_data.iloc[ind_pivots_min[-1]]
                i_min_prev = indicator_data.iloc[ind_pivots_min[-2]]
                
                # Regular Bullish: Price Lower Low, Indicator Higher Low
                if p_min_curr < p_min_prev and i_min_curr > i_min_prev:
                    results["regular_bullish"] = True
                
                # Hidden Bullish: Price Higher Low, Indicator Lower Low
                if p_min_curr > p_min_prev and i_min_curr < i_min_prev:
                    results["hidden_bullish"] = True

            if len(price_pivots_max) >= 2 and len(ind_pivots_max) >= 2:
                # Check Maxima (Bearish Divergences)
                p_max_curr = price_data.iloc[price_pivots_max[-1]]
                p_max_prev = price_data.iloc[price_pivots_max[-2]]
                
                i_max_curr = indicator_data.iloc[ind_pivots_max[-1]]
                i_max_prev = indicator_data.iloc[ind_pivots_max[-2]]
                
                # Regular Bearish: Price Higher High, Indicator Lower High
                if p_max_curr > p_max_prev and i_max_curr < i_max_prev:
                    results["regular_bearish"] = True
                    
                # Hidden Bearish: Price Lower High, Indicator Higher High
                if p_max_curr < p_max_prev and i_max_curr > i_max_prev:
                    results["hidden_bearish"] = True

            return results

        except Exception as e:
            logger.error(f"Error detecting divergence: {e}")
            return {
                "regular_bullish": False,
                "regular_bearish": False,
                "hidden_bullish": False,
                "hidden_bearish": False
            }

    @staticmethod
    def support_resistance_levels(
        data: pd.DataFrame, window: int = 20, min_touches: int = 2
    ) -> dict:
        """Identify support and resistance levels."""
        try:
            high = data["high"]
            low = data["low"]

            # Find pivot highs and lows
            pivot_highs = TechnicalIndicators.find_pivots(high, window // 2)
            pivot_lows = TechnicalIndicators.find_pivots(
                -low, window // 2
            )  # Negative for minima

            # Get pivot values
            resistance_levels: List[float] = (
                high.iloc[np.array(pivot_highs)].values.tolist() if pivot_highs else []
            )
            support_levels: List[float] = (
                low.iloc[np.array(pivot_lows)].values.tolist() if pivot_lows else []
            )

            # Cluster similar levels
            def cluster_levels(levels, tolerance=0.01):
                if len(levels) == 0:
                    return []

                clustered = []
                levels = sorted(levels)

                current_cluster = [levels[0]]

                for level in levels[1:]:
                    if (
                        abs(level - current_cluster[-1]) / current_cluster[-1]
                        <= tolerance
                    ):
                        current_cluster.append(level)
                    else:
                        if len(current_cluster) >= min_touches:
                            clustered.append(np.mean(current_cluster))
                        current_cluster = [level]

                if len(current_cluster) >= min_touches:
                    clustered.append(np.mean(current_cluster))

                return clustered

            support_levels = cluster_levels(support_levels)
            resistance_levels = cluster_levels(resistance_levels)

            return {"support": support_levels, "resistance": resistance_levels}

        except Exception as e:
            logger.error(f"Error finding support/resistance: {e}")
            return {"support": [], "resistance": []}

    @staticmethod
    def volume_profile(data: pd.DataFrame, bins: int = 50) -> dict:
        """Calculate volume profile."""
        try:
            if "volume" not in data.columns:
                return {"prices": [], "volumes": []}

            # Create price bins
            price_min = data["low"].min()
            price_max = data["high"].max()
            price_bins = np.linspace(price_min, price_max, bins + 1)

            # Calculate volume at each price level
            volume_at_price = np.zeros(bins)

            for i, row in data.iterrows():
                # Distribute volume across the price range of the bar
                high_price = row["high"]
                low_price = row["low"]
                volume = row["volume"]

                # Find which bins this bar spans
                start_bin = np.digitize(low_price, price_bins) - 1
                end_bin = np.digitize(high_price, price_bins) - 1

                start_bin = max(0, min(start_bin, bins - 1))
                end_bin = max(0, min(end_bin, bins - 1))

                # Distribute volume evenly across bins
                bins_spanned = max(1, end_bin - start_bin + 1)
                volume_per_bin = volume / bins_spanned

                for bin_idx in range(start_bin, end_bin + 1):
                    if 0 <= bin_idx < bins:
                        volume_at_price[bin_idx] += volume_per_bin

            # Get bin centers
            bin_centers = (price_bins[:-1] + price_bins[1:]) / 2

            return {"prices": bin_centers.tolist(), "volumes": volume_at_price.tolist()}

        except Exception as e:
            logger.error(f"Error calculating volume profile: {e}")
            return {"prices": [], "volumes": []}

    @staticmethod
    def vwap(data: pd.DataFrame) -> pd.Series:
        """Volume Weighted Average Price (Session/Cumulative)."""
        v = data["volume"]
        tp = (data["high"] + data["low"] + data["close"]) / 3
        return (tp * v).cumsum() / v.cumsum()

    @staticmethod
    def rolling_vwap(data: pd.DataFrame, window: int = 20) -> pd.Series:
        """Rolling Volume Weighted Average Price."""
        v = data["volume"]
        tp = (data["high"] + data["low"] + data["close"]) / 3
        
        pv = tp * v
        
        rolling_pv = pv.rolling(window=window).sum()
        rolling_vol = v.rolling(window=window).sum()
        
        return rolling_pv / rolling_vol

    @staticmethod
    def ema_ribbon(data: pd.Series, periods: List[int] = None) -> pd.DataFrame:
        """EMA Ribbon."""
        if periods is None:
            periods = [8, 13, 21, 34, 55]
        
        ribbon = pd.DataFrame(index=data.index)
        for period in periods:
            ribbon[f"EMA_{period}"] = TechnicalIndicators.ema(data, period)
        
        return ribbon

    @staticmethod
    def wavetrend_cipher_b(
        data: pd.DataFrame, 
        n1: int = 10, 
        n2: int = 21
    ) -> pd.DataFrame:
        """
        VuMan Chu Cipher B (WaveTrend) implementation.
        Returns a DataFrame with:
        - wt1: WaveTrend 1
        - wt2: WaveTrend 2
        - vwap: Money Flow (approx)
        """
        # Approximate Money Flow (HLC3)
        ap = (data["high"] + data["low"] + data["close"]) / 3
        
        # ESA = EMA(AP, n1)
        esa = TechnicalIndicators.ema(ap, n1)
        
        # D = EMA(abs(AP - ESA), n1)
        d = TechnicalIndicators.ema((ap - esa).abs(), n1)
        
        # CI = (AP - ESA) / (0.015 * D)
        ci = (ap - esa) / (0.015 * d)
        
        # TCI = EMA(CI, n2)
        tci = TechnicalIndicators.ema(ci, n2)
        
        # WaveTrend
        wt1 = tci
        wt2 = TechnicalIndicators.sma(wt1, 4)
        
        return pd.DataFrame({
            "wt1": wt1,
            "wt2": wt2,
            "diff": wt1 - wt2
        })
