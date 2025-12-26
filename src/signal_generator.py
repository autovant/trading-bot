import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from src.config import StrategyConfig
from src.indicators import TechnicalIndicators
from src.models import MarketRegime, TradingSetup, TradingSignal

logger = logging.getLogger(__name__)


class SignalGenerator:
    """
    Handles signal generation logic based on market data and configured indicators.
    Decoupled from TradingStrategy to improve testability and maintainability.
    """

    def __init__(self, indicators: Optional[TechnicalIndicators] = None):
        self.indicators = indicators or TechnicalIndicators()

    def detect_regime(self, data: pd.DataFrame, config: StrategyConfig) -> MarketRegime:
        """Detect market regime using daily timeframe."""
        try:
            # Calculate indicators
            ema_200 = self.indicators.ema(data["close"], config.regime.ema_period)
            macd_line, _, _ = self.indicators.macd(
                data["close"],
                config.regime.macd_fast,
                config.regime.macd_slow,
                config.regime.macd_signal,
            )

            if ema_200.empty or macd_line.empty:
                logger.warning("Insufficient data for regime detection")
                return MarketRegime(regime="neutral", strength=0.0, confidence=0.0)

            # Current values
            current_price = data["close"].iloc[-1]
            current_ema = ema_200.iloc[-1]
            current_macd = macd_line.iloc[-1]

            # Determine regime
            if current_price > current_ema and current_macd > 0:
                regime = "bullish"
                strength = min(1.0, (current_price - current_ema) / current_ema * 10)
            elif current_price < current_ema and current_macd < 0:
                regime = "bearish"
                strength = min(1.0, (current_ema - current_price) / current_ema * 10)
            else:
                regime = "neutral"
                strength = 0.5

            # Calculate confidence based on alignment
            price_ema_align = (
                1.0 if (current_price > current_ema) == (current_macd > 0) else 0.3
            )
            confidence = strength * price_ema_align

            return MarketRegime(regime=regime, strength=strength, confidence=confidence)

        except Exception as e:
            logger.error(f"Error detecting regime: {e}")
            return MarketRegime(regime="neutral", strength=0.5, confidence=0.5)

    def detect_setup(self, data: pd.DataFrame, config: StrategyConfig) -> TradingSetup:
        """Detect trading setup using 4-hour timeframe."""
        try:
            # Calculate EMAs
            ema_8 = self.indicators.ema(data["close"], config.setup.ema_fast)
            ema_21 = self.indicators.ema(data["close"], config.setup.ema_medium)
            ema_55 = self.indicators.ema(data["close"], config.setup.ema_slow)

            # Calculate ADX and ATR
            adx = self.indicators.adx(data, config.setup.adx_period)
            atr = self.indicators.atr(data, config.setup.atr_period)

            if ema_55.empty or adx.empty or atr.empty:
                return TradingSetup(direction="none", quality=0.0, strength=0.0)

            # Current values
            current_price = data["close"].iloc[-1]
            current_ema8 = ema_8.iloc[-1]
            current_ema21 = ema_21.iloc[-1]
            current_ema55 = ema_55.iloc[-1]
            current_adx = adx.iloc[-1]
            current_atr = atr.iloc[-1]

            # Check EMA stack alignment
            bullish_stack = current_ema8 > current_ema21 > current_ema55
            bearish_stack = current_ema8 < current_ema21 < current_ema55

            # Check trend strength
            strong_trend = current_adx > config.setup.adx_threshold

            # Check price proximity to EMA8
            price_distance = abs(current_price - current_ema8)
            max_distance = current_atr * config.setup.atr_multiplier
            price_near_ema = price_distance <= max_distance

            # Determine setup
            if bullish_stack and strong_trend and price_near_ema:
                direction = "long"
                quality = min(1.0, current_adx / 50.0)  # Normalize ADX
                strength = (
                    1.0 - (price_distance / max_distance) if max_distance > 0 else 0.0
                )
            elif bearish_stack and strong_trend and price_near_ema:
                direction = "short"
                quality = min(1.0, current_adx / 50.0)
                strength = (
                    1.0 - (price_distance / max_distance) if max_distance > 0 else 0.0
                )
            else:
                direction = "none"
                quality = 0.0
                strength = 0.0

            return TradingSetup(direction=direction, quality=quality, strength=strength)

        except Exception as e:
            logger.error(f"Error detecting setup: {e}")
            return TradingSetup(direction="none", quality=0.0, strength=0.0)

    def generate_signals(
        self, data: pd.DataFrame, config: StrategyConfig
    ) -> List[TradingSignal]:
        """Generate trading signals using 1-hour timeframe."""
        signals = []

        try:
            # Calculate indicators
            ema_21 = self.indicators.ema(data["close"], 21)
            rsi = self.indicators.rsi(data["close"], config.signals.rsi_period)
            donchian_high, donchian_low = self.indicators.donchian_channels(
                data, config.signals.donchian_period
            )
            bb_upper, bb_middle, bb_lower = self.indicators.bollinger_bands(
                data["close"],
                config.signals.bollinger_period,
                config.signals.bollinger_std_dev,
            )
            divergence = self.indicators.detect_divergence(
                data["close"],
                rsi,
                config.signals.divergence_lookback,
            )

            if ema_21.empty or rsi.empty:
                return []

            # Current values
            current_price = float(data["close"].iloc[-1])
            current_ema21 = float(ema_21.iloc[-1])
            current_rsi = float(rsi.iloc[-1])
            current_high = float(donchian_high.iloc[-1])
            current_low = float(donchian_low.iloc[-1])
            current_bb_upper = float(bb_upper.iloc[-1])
            current_bb_middle = float(bb_middle.iloc[-1])
            current_bb_lower = float(bb_lower.iloc[-1])

            # 1. Pullback Signals
            if (
                current_price <= current_ema21 * 1.005
                and current_price >= current_ema21 * 0.995
                and current_rsi < config.signals.rsi_oversold
            ):
                signals.append(
                    TradingSignal(
                        signal_type="pullback",
                        direction="long",
                        strength=0.8,
                        confidence=0.7,
                        entry_price=current_price,
                        stop_loss=current_price * 0.98,
                        take_profit=current_price * 1.04,
                        timestamp=datetime.now(timezone.utc),
                    )
                )

            elif (
                current_price <= current_ema21 * 1.005
                and current_price >= current_ema21 * 0.995
                and current_rsi > config.signals.rsi_overbought
            ):
                signals.append(
                    TradingSignal(
                        signal_type="pullback",
                        direction="short",
                        strength=0.8,
                        confidence=0.7,
                        entry_price=current_price,
                        stop_loss=current_price * 1.02,
                        take_profit=current_price * 0.96,
                        timestamp=datetime.now(timezone.utc),
                    )
                )

            # 2. Breakout Signals
            if current_price > current_high:
                signals.append(
                    TradingSignal(
                        signal_type="breakout",
                        direction="long",
                        strength=0.9,
                        confidence=0.8,
                        entry_price=current_price,
                        stop_loss=current_low,
                        take_profit=current_price + 2 * (current_price - current_low),
                        timestamp=datetime.now(timezone.utc),
                    )
                )

            elif current_price < current_low:
                signals.append(
                    TradingSignal(
                        signal_type="breakout",
                        direction="short",
                        strength=0.9,
                        confidence=0.8,
                        entry_price=current_price,
                        stop_loss=current_high,
                        take_profit=current_price - 2 * (current_high - current_price),
                        timestamp=datetime.now(timezone.utc),
                    )
                )

            # 3. Mean Reversion (Bollinger Bands)
            if current_price <= current_bb_lower:
                signals.append(
                    TradingSignal(
                        signal_type="mean_reversion",
                        direction="long",
                        strength=0.7,
                        confidence=0.6,
                        entry_price=current_price,
                        stop_loss=current_price * 0.98,
                        take_profit=current_bb_middle,
                        timestamp=datetime.now(timezone.utc),
                    )
                )
            elif current_price >= current_bb_upper:
                signals.append(
                    TradingSignal(
                        signal_type="mean_reversion",
                        direction="short",
                        strength=0.7,
                        confidence=0.6,
                        entry_price=current_price,
                        stop_loss=current_price * 1.02,
                        take_profit=current_bb_middle,
                        timestamp=datetime.now(timezone.utc),
                    )
                )

            # 4. Divergence Signals
            if divergence.get("bullish"):
                signals.append(
                    TradingSignal(
                        signal_type="divergence",
                        direction="long",
                        strength=0.85,
                        confidence=0.75,
                        entry_price=current_price,
                        stop_loss=current_price * 0.98,
                        take_profit=current_price * 1.05,
                        timestamp=datetime.now(timezone.utc),
                    )
                )
            elif divergence.get("bearish"):
                signals.append(
                    TradingSignal(
                        signal_type="divergence",
                        direction="short",
                        strength=0.85,
                        confidence=0.75,
                        entry_price=current_price,
                        stop_loss=current_price * 1.02,
                        take_profit=current_price * 0.95,
                        timestamp=datetime.now(timezone.utc),
                    )
                )

        except Exception as e:
            logger.error(f"Error generating signals: {e}")

        return signals

    def filter_signals(
        self, signals: List[TradingSignal], regime: MarketRegime, setup: TradingSetup
    ) -> List[TradingSignal]:
        """Filter signals based on market regime and setup."""
        if not signals:
            return []

        valid_signals = []
        for signal in signals:
            # Check regime alignment
            regime_aligned = (
                signal.direction == "long" and regime.regime in ["bullish", "neutral"]
            ) or (
                signal.direction == "short" and regime.regime in ["bearish", "neutral"]
            )

            # Check setup alignment
            setup_aligned = (
                setup.direction == "none"  # No setup bias
                or signal.direction == setup.direction
            )

            if regime_aligned and setup_aligned:
                valid_signals.append(signal)

        return valid_signals

    def apply_microstructure_filters(
        self,
        signals: List[TradingSignal],
        vwap_val: Optional[float],
        ob_metrics: Dict[str, Any],
        config: StrategyConfig,
    ) -> List[TradingSignal]:
        """Filter signals based on VWAP and Order Book metrics."""
        if not signals:
            return []

        filtered_signals = []

        for signal in signals:
            keep = True

            # VWAP Filter
            if config.vwap.enabled and vwap_val is not None:
                if (
                    signal.direction == "long"
                    and config.vwap.require_price_above_vwap_for_longs
                ):
                    if signal.entry_price < vwap_val:
                        keep = False
                        logger.debug(
                            f"Signal filtered by VWAP: "
                            f"{signal.entry_price:.2f} < {vwap_val:.2f}"
                        )
                elif (
                    signal.direction == "short"
                    and config.vwap.require_price_below_vwap_for_shorts
                ):
                    if signal.entry_price > vwap_val:
                        keep = False
                        logger.debug(
                            f"Signal filtered by VWAP: "
                            f"{signal.entry_price:.2f} > {vwap_val:.2f}"
                        )

            # Order Book Filter
            if config.orderbook.enabled and config.orderbook.use_for_entry:
                imbalance = ob_metrics.get("imbalance", 0.0)
                threshold = config.orderbook.imbalance_threshold

                if signal.direction == "long":
                    if imbalance < threshold:
                        keep = False
                        logger.debug(
                            f"Signal filtered by OBI: {imbalance:.2f} < {threshold}"
                        )
                elif signal.direction == "short":
                    if imbalance > -threshold:
                        keep = False
                        logger.debug(
                            f"Signal filtered by OBI: {imbalance:.2f} > {-threshold}"
                        )

            if keep:
                filtered_signals.append(signal)

        return filtered_signals
