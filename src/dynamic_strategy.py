"""
Dynamic Strategy Engine.
Allows defining trading strategies using a JSON/YAML configuration.
"""

import logging
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from pydantic import BaseModel

from .indicators import TechnicalIndicators
from .models import ConfidenceScore, MarketRegime, TradingSetup, TradingSignal

logger = logging.getLogger(__name__)


class IndicatorConfig(BaseModel):
    """Configuration for an indicator."""

    name: str
    params: Dict[str, Any] = {}


class ConditionConfig(BaseModel):
    """Configuration for a logic condition."""

    indicator_a: Union[str, float, int]  # e.g., "ema_200" or 50
    operator: str  # ">", "<", "==", ">=", "<=", "crosses_above", "crosses_below"
    indicator_b: Union[str, float, int]  # e.g., "close" or 0


class RegimeConfig(BaseModel):
    """Configuration for regime detection."""

    timeframe: str = "1d"
    indicators: List[IndicatorConfig] = []
    bullish_conditions: List[ConditionConfig] = []
    bearish_conditions: List[ConditionConfig] = []
    weight: float = 0.25


class SetupConfig(BaseModel):
    """Configuration for setup detection."""

    timeframe: str = "4h"
    indicators: List[IndicatorConfig] = []
    bullish_conditions: List[ConditionConfig] = []
    bearish_conditions: List[ConditionConfig] = []
    weight: float = 0.30


class SignalConfig(BaseModel):
    """Configuration for signal generation."""

    timeframe: str = "1h"
    indicators: List[IndicatorConfig] = []
    entry_conditions: List[ConditionConfig] = []
    exit_conditions: List[ConditionConfig] = []  # Optional, for specific exits
    signal_type: str = "custom"  # e.g. "pullback", "breakout"
    direction: str = "long"  # "long" or "short"
    weight: float = 0.35


class RiskConfig(BaseModel):
    """Configuration for risk management."""

    stop_loss_type: str = "atr"  # "atr", "percent", "fixed"
    stop_loss_value: float = 1.5  # Multiplier for ATR, or percentage
    take_profit_type: str = "risk_reward"  # "risk_reward", "percent", "fixed"
    take_profit_value: float = 2.0  # R:R ratio
    max_drawdown_limit: float = 0.15


class StrategyConfig(BaseModel):
    """Complete strategy configuration."""

    name: str
    description: str = ""
    regime: RegimeConfig
    setup: SetupConfig
    signals: List[SignalConfig]
    risk: RiskConfig
    confidence_threshold: float = 70.0


class DynamicStrategyEngine:
    """Engine to execute dynamic strategies."""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.indicators = TechnicalIndicators()

    def _calculate_indicators(
        self, data: pd.DataFrame, indicators_config: List[IndicatorConfig]
    ) -> pd.DataFrame:
        """Calculate requested indicators and add them to the dataframe."""
        df = data.copy()

        # Always ensure we have basic OHLCV
        required_cols = ["open", "high", "low", "close", "volume"]
        if not all(col in df.columns for col in required_cols):
            # Try to map if case mismatch
            df.columns = pd.Index([c.lower() for c in df.columns])

        for ind in indicators_config:
            try:
                if ind.name == "ema":
                    period = ind.params.get("period", 14)
                    source = ind.params.get("source", "close")
                    if source in df.columns:
                        df[f"ema_{period}"] = self.indicators.ema(df[source], period)
                elif ind.name == "sma":
                    period = ind.params.get("period", 14)
                    source = ind.params.get("source", "close")
                    if source in df.columns:
                        df[f"sma_{period}"] = self.indicators.sma(df[source], period)
                elif ind.name == "rsi":
                    period = ind.params.get("period", 14)
                    df[f"rsi_{period}"] = self.indicators.rsi(df["close"], period)
                elif ind.name == "macd":
                    fast = ind.params.get("fast", 12)
                    slow = ind.params.get("slow", 26)
                    signal = ind.params.get("signal", 9)
                    m, s, h = self.indicators.macd(df["close"], fast, slow, signal)
                    df["macd"] = m
                    df["macd_signal"] = s
                    df["macd_hist"] = h
                elif ind.name == "atr":
                    period = ind.params.get("period", 14)
                    df[f"atr_{period}"] = self.indicators.atr(df, period)
                elif ind.name == "adx":
                    period = ind.params.get("period", 14)
                    df[f"adx_{period}"] = self.indicators.adx(df, period)
                elif ind.name == "bollinger_bands":
                    period = ind.params.get("period", 20)
                    std = ind.params.get("std_dev", 2.0)
                    upper, middle, lower = self.indicators.bollinger_bands(
                        df["close"], period, std
                    )
                    df["bb_upper"] = upper
                    df["bb_middle"] = middle
                    df["bb_lower"] = lower
                    df["bb_width"] = (upper - lower) / middle
                elif ind.name == "divergence":
                    # source_a is usually price (low/high), source_b is oscillator
                    oscillator = ind.params.get("oscillator", "rsi_14")
                    lookback = ind.params.get("lookback", 3)

                    # Ensure oscillator exists
                    if oscillator not in df.columns:
                        # Try to calculate it if it's a standard one and not present?
                        # For now, assume it's already calculated or will be calculated if listed before.
                        # Ideally, we should dependency sort, but for now rely on config order.
                        logger.warning(
                            f"Oscillator {oscillator} not found for divergence check."
                        )
                        continue

                    # We need to run detection on the whole series or a rolling window?
                    # detect_divergence returns a dict for the *end* of the series.
                    # To populate a column, we'd need to run it rolling.
                    # However, running rolling pivot detection is expensive.
                    # For backtesting, we might need it. For live, we just need the last one.
                    # Let's implement a simplified rolling version or just apply to the whole series
                    # and assume the 'detect_divergence' function can handle finding pivots across the whole series
                    # and then we map the results to the dataframe.

                    # Actually, detect_divergence as written returns a single dict for the *current* state
                    # based on the last few pivots. It doesn't return a series.
                    # We need to adapt it or iterate.
                    # Iterating is slow in Python.
                    # Let's assume for now we only care about the *latest* value for live trading.
                    # But for backtesting (which uses this same engine), we need the full series.

                    # Let's create a helper to generate divergence series.
                    # For now, to keep it simple and performant enough:
                    # We will just initialize the columns with 0.
                    # And only populate the last row if we are in live mode?
                    # No, backtest needs history.

                    # Let's skip full historical divergence for now and just implement it
                    # as a check on the *current* row in _evaluate_condition?
                    # No, _evaluate_condition takes a row.

                    # OK, let's implement a vectorized-ish approach.
                    # We can find ALL pivots in the series at once.
                    # Then iterate through pivots to mark divergences.
                    # This is much faster than sliding window.

                    # Initialize columns
                    base_name = f"{oscillator}_div"
                    df[f"{base_name}_reg_bull"] = 0.0
                    df[f"{base_name}_reg_bear"] = 0.0
                    df[f"{base_name}_hid_bull"] = 0.0
                    df[f"{base_name}_hid_bear"] = 0.0

                    # Map pivots to indices for quick lookup
                    # Actually, we can just iterate through the pivots and check conditions

                    # Regular Bullish: Price Lows Lower, Osc Lows Higher
                    # We need to match price pivots with osc pivots that are "close" in time?
                    # Or just look at the sequence of pivots?
                    # Standard divergence usually compares the most recent two pivots.
                    # So we can just iterate through the pivots list.

                    def mark_divergences(p_pivots, o_pivots, p_data, o_data, is_lows):
                        # This is a simplification. Matching exact pivots is tricky.
                        # We'll use a simplified approach:
                        # For each pivot in Price, look for a nearby pivot in Oscillator.
                        # If found, compare with previous pair.
                        pass

                    # Given the complexity of vectorizing this correctly for backtesting without
                    # a dedicated library, we will use a simplified approach:
                    # We will use the `detect_divergence` function which works on the *end* of data.
                    # For backtesting, this engine might be slow if we re-run it every bar.
                    # But `DynamicStrategyEngine` is designed to run on a dataframe.
                    # If we are backtesting, we are likely passing the whole dataframe?
                    # No, the backtester usually iterates.
                    # If the backtester iterates and calls `generate_signals` with a window of data,
                    # then calling `detect_divergence` on that window is fine.

                    # So, we will just run `detect_divergence` on the provided dataframe
                    # and populate the *last* row.
                    # This assumes the engine is called iteratively (which it is in the backtester).

                    divs = self.indicators.detect_divergence(
                        df["low"], df[oscillator], lookback
                    )
                    # We also need high for bearish
                    divs_high = self.indicators.detect_divergence(
                        df["high"], df[oscillator], lookback
                    )

                    # Merge results
                    # detect_divergence checks both if we pass the same series,
                    # but for price we should pass Low for Bullish and High for Bearish.
                    # The current implementation of detect_divergence uses one price series.
                    # So we call it twice.

                    # Bullish checks (using lows)
                    last_index = df.index[-1]
                    if divs["regular_bullish"]:
                        df.at[last_index, f"{base_name}_reg_bull"] = 1.0
                    if divs["hidden_bullish"]:
                        df.at[last_index, f"{base_name}_hid_bull"] = 1.0

                    # Bearish checks (using highs)
                    if divs_high["regular_bearish"]:
                        df.at[last_index, f"{base_name}_reg_bear"] = 1.0
                    if divs_high["hidden_bearish"]:
                        df.at[last_index, f"{base_name}_hid_bear"] = 1.0

                # Add more indicators as needed
            except Exception as e:
                logger.error(f"Error calculating indicator {ind.name}: {e}")

        return df

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _evaluate_condition(self, row: pd.Series, condition: ConditionConfig) -> bool:
        """Evaluate a single condition for a row."""
        try:
            # Get values
            val_a: Any = (
                row.get(condition.indicator_a)
                if isinstance(condition.indicator_a, str)
                and condition.indicator_a in row
                else condition.indicator_a
            )
            val_b: Any = (
                row.get(condition.indicator_b)
                if isinstance(condition.indicator_b, str)
                and condition.indicator_b in row
                else condition.indicator_b
            )

            # Handle string literals if they were passed as "strings" in config but meant to be column names that don't exist?
            # No, assuming config is correct.

            if isinstance(val_a, str) and val_a in row:
                val_a = row[val_a]
            if isinstance(val_b, str) and val_b in row:
                val_b = row[val_b]

            a_num = self._as_float(val_a)
            b_num = self._as_float(val_b)
            if a_num is None or b_num is None:
                return False

            if condition.operator == ">":
                return a_num > b_num
            elif condition.operator == "<":
                return a_num < b_num
            elif condition.operator == "==":
                return a_num == b_num
            elif condition.operator == ">=":
                return a_num >= b_num
            elif condition.operator == "<=":
                return a_num <= b_num
            # Crosses logic requires previous row, which is hard with just 'row'.
            # For now, we'll assume simple state checks.
            # Real 'cross' logic needs the full series or prev_row.
            # We will implement 'crosses' by checking current vs prev in the main loop if needed,
            # but for this row-based check, we stick to state.

            return False
        except Exception:
            return False

    def detect_regime(self, data: pd.DataFrame) -> MarketRegime:
        """Detect market regime based on config."""
        if data.empty:
            return MarketRegime(regime="neutral", strength=0.0, confidence=0.0)

        df = self._calculate_indicators(data, self.config.regime.indicators)
        current = df.iloc[-1]

        bullish = (
            all(
                self._evaluate_condition(current, c)
                for c in self.config.regime.bullish_conditions
            )
            if self.config.regime.bullish_conditions
            else False
        )
        bearish = (
            all(
                self._evaluate_condition(current, c)
                for c in self.config.regime.bearish_conditions
            )
            if self.config.regime.bearish_conditions
            else False
        )

        if bullish:
            return MarketRegime(regime="bullish", strength=1.0, confidence=1.0)
        elif bearish:
            return MarketRegime(regime="bearish", strength=1.0, confidence=1.0)
        else:
            return MarketRegime(regime="neutral", strength=0.5, confidence=0.5)

    def detect_setup(self, data: pd.DataFrame) -> TradingSetup:
        """Detect trading setup based on config."""
        if data.empty:
            return TradingSetup(direction="none", quality=0.0, strength=0.0)

        df = self._calculate_indicators(data, self.config.setup.indicators)
        current = df.iloc[-1]

        bullish = (
            all(
                self._evaluate_condition(current, c)
                for c in self.config.setup.bullish_conditions
            )
            if self.config.setup.bullish_conditions
            else False
        )
        bearish = (
            all(
                self._evaluate_condition(current, c)
                for c in self.config.setup.bearish_conditions
            )
            if self.config.setup.bearish_conditions
            else False
        )

        if bullish:
            return TradingSetup(direction="long", quality=1.0, strength=1.0)
        elif bearish:
            return TradingSetup(direction="short", quality=1.0, strength=1.0)
        else:
            return TradingSetup(direction="none", quality=0.0, strength=0.0)

    def generate_signals(self, data: pd.DataFrame) -> List[TradingSignal]:
        """Generate signals based on config."""
        if data.empty:
            return []

        signals = []

        for sig_config in self.config.signals:
            df = self._calculate_indicators(data, sig_config.indicators)
            current = df.iloc[-1]

            # Check entry conditions
            entry_met = all(
                self._evaluate_condition(current, c)
                for c in sig_config.entry_conditions
            )

            logger.debug(
                "Checking signal %s: entry_met=%s", sig_config.signal_type, entry_met
            )

            if entry_met:
                # Calculate stop loss and take profit based on risk config
                # This is a simplified version; real logic might use ATR from the dataframe
                current_price = current["close"]

                stop_loss = 0.0
                take_profit = 0.0

                # Try to get ATR if configured
                atr_val = 0.0
                for col in df.columns:
                    if col.startswith("atr_"):
                        atr_val = df[col].iloc[-1]
                        break

                if self.config.risk.stop_loss_type == "atr" and atr_val > 0:
                    sl_dist = atr_val * self.config.risk.stop_loss_value
                    if sig_config.direction == "long":
                        stop_loss = current_price - sl_dist
                    else:
                        stop_loss = current_price + sl_dist
                elif self.config.risk.stop_loss_type == "percent":
                    sl_dist = current_price * (self.config.risk.stop_loss_value / 100.0)
                    if sig_config.direction == "long":
                        stop_loss = current_price - sl_dist
                    else:
                        stop_loss = current_price + sl_dist

                if self.config.risk.take_profit_type == "risk_reward" and stop_loss > 0:
                    risk = abs(current_price - stop_loss)
                    reward = risk * self.config.risk.take_profit_value
                    if sig_config.direction == "long":
                        take_profit = current_price + reward
                    else:
                        take_profit = current_price - reward
                elif self.config.risk.take_profit_type == "percent":
                    tp_dist = current_price * (
                        self.config.risk.take_profit_value / 100.0
                    )
                    if sig_config.direction == "long":
                        take_profit = current_price + tp_dist
                    else:
                        take_profit = current_price - tp_dist

                signals.append(
                    TradingSignal(
                        signal_type=sig_config.signal_type,
                        direction=sig_config.direction,
                        strength=1.0,
                        confidence=1.0,
                        entry_price=current_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        source=self.config.name,
                    )
                )

        return signals

    def calculate_confidence(
        self, regime: MarketRegime, setup: TradingSetup, signal: TradingSignal
    ) -> ConfidenceScore:
        """Calculate confidence score."""
        # Simple weighted sum
        regime_score = regime.confidence * self.config.regime.weight * 100
        setup_score = setup.strength * self.config.setup.weight * 100
        signal_score = (
            signal.strength * 0.35 * 100
        )  # Default weight for signal if not in config

        # Find the specific signal config weight if possible
        # For now use default

        total = regime_score + setup_score + signal_score
        return ConfidenceScore(
            regime_score=regime_score,
            setup_score=setup_score,
            signal_score=signal_score,
            penalty_score=0,
            total_score=total,
        )
