import logging
from typing import Dict, Optional

import pandas as pd

from src.config import StrategyConfig, TradingBotConfig
from src.indicators import TechnicalIndicators
from src.models import (
    ConfidenceScore,
    MarketRegime,
    TradingSetup,
    TradingSignal,
)

logger = logging.getLogger(__name__)


class PositionManager:
    """
    Handles position sizing, stop-loss calculations, and risk-adjusted order parameter preparation.
    """

    def __init__(self, indicators: Optional[TechnicalIndicators] = None):
        self.indicators = indicators or TechnicalIndicators()

    def calculate_confidence(
        self,
        regime: MarketRegime,
        setup: TradingSetup,
        signal: TradingSignal,
        config: StrategyConfig,
        market_data: Optional[Dict[str, pd.DataFrame]] = None,
        symbol: str = "",
    ) -> ConfidenceScore:
        """Calculate confidence score for a trading signal."""

        # Regime score
        regime_score = regime.confidence * config.regime.weight * 100

        # Setup score
        setup_score = (setup.quality * setup.strength) * config.setup.weight * 100

        # Signal score
        signal_score = (
            (signal.strength * signal.confidence) * config.signals.weight * 100
        )

        # Calculate penalties
        penalty_score = 0

        try:
            if market_data and symbol in market_data:
                signal_data = market_data[symbol]
                # Check if it's a DataFrame or dictionary
                if isinstance(signal_data, dict) and "signal" in signal_data:
                    signal_data = signal_data["signal"]

                if isinstance(signal_data, pd.DataFrame) and not signal_data.empty:
                    atr = self.indicators.atr(signal_data, 14)
                    if not atr.empty:
                        avg_atr = atr.rolling(50).mean().iloc[-1]
                        current_atr = atr.iloc[-1]

                        if current_atr > avg_atr * 2:
                            penalty_score += config.confidence.penalties.get(
                                "high_volatility", 0
                            )

                    # Low volume penalty
                    if "volume" in signal_data.columns:
                        avg_volume = signal_data["volume"].rolling(20).mean().iloc[-1]
                        current_volume = signal_data["volume"].iloc[-1]

                        if current_volume < avg_volume * 0.8:
                            penalty_score += config.confidence.penalties.get(
                                "low_volume", 0
                            )

            # Conflicting timeframes penalty
            if regime.regime != "neutral" and setup.direction != "none":
                if (regime.regime == "bullish" and setup.direction == "short") or (
                    regime.regime == "bearish" and setup.direction == "long"
                ):
                    penalty_score += config.confidence.penalties.get(
                        "conflicting_timeframes", 0
                    )

        except Exception as e:
            logger.error(f"Error calculating penalties: {e}")

        # Total score
        total_score = max(0, regime_score + setup_score + signal_score + penalty_score)

        return ConfidenceScore(
            regime_score=regime_score,
            setup_score=setup_score,
            signal_score=signal_score,
            penalty_score=penalty_score,
            total_score=total_score,
        )

    def calculate_position_size(
        self,
        signal: TradingSignal,
        confidence: ConfidenceScore,
        account_balance: float,
        initial_capital: float,
        config: TradingBotConfig,
        crisis_mode: bool = False,
    ) -> float:
        """Calculate position size based on risk management rules."""
        try:
            # 1. Start with account balance
            working_capital = initial_capital + (account_balance - initial_capital)
            if working_capital <= 0:
                return 0.0

            if crisis_mode:
                working_capital *= (
                    1 - config.risk_management.crisis_mode.position_size_reduction
                )

            # 2. Base Risk Amount
            risk_per_trade = working_capital * config.trading.risk_per_trade

            # 3. Adjust for confidence
            size_multiplier = 0.7
            if confidence is not None:
                if (
                    confidence.total_score
                    >= config.strategy.confidence.full_size_threshold
                ):
                    size_multiplier = 1.0
                elif confidence.total_score < config.strategy.confidence.min_threshold:
                    return 0.0

            risk_amount = risk_per_trade * size_multiplier

            # 4. Calculate position size based on stop loss distance
            entry_price = signal.entry_price
            stop_loss = signal.stop_loss

            if entry_price <= 0 or stop_loss <= 0:
                return 0.0

            risk_per_unit = abs(entry_price - stop_loss)

            if risk_per_unit == 0:
                return 0.0

            position_size = risk_amount / risk_per_unit

            # 5. Cap at max position size (simple check if configured, though config might not have it explicitly in trading.max_positions but we respect logical max)
            # Implemented as checking risk logic or max notional if added to config.
            # config.trading.max_sector_exposure could be used, but for now we stick to risk_per_trade.

            return position_size

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0.0

    def check_rebalance_needed(
        self,
        positions: list,
        account_balance: float,
        config: TradingBotConfig,
    ) -> list:
        """
        Check if any active positions need rebalancing (trimming oversized positions).
        Returns a list of actions, e.g. [{'symbol': 'BTC/USD', 'action': 'trim', 'quantity': 0.5}].
        """
        actions = []
        try:
            # simple logic: if position value > 2x max_risk allocated value (approx)
            # strictly speaking we should look at max_position_size config if it exists
            # but using risk_per_trade as proxy for 'intended size' basis
            
            # Allow 50% drift from "max ideal size"
            # Assuming ideal size ~ (balance * risk_per_trade) / (ATR risk %)
            # This is hard without knowing entry ATR. 
            
            # Alternative: simpler fixed pct of portfolio
            # If any single position > 20% of equity (example hard cap)
            max_single_position_value = account_balance * 0.20 
            
            for pos in positions:
                # pos is assumed to be an object with .size, .mark_price, .symbol
                # If pos is dict, access accordingly
                size = getattr(pos, 'size', 0)
                price = getattr(pos, 'mark_price', 0) or getattr(pos, 'entry_price', 0)
                symbol = getattr(pos, 'symbol', 'UNKNOWN')
                
                current_value = size * price
                
                if current_value > max_single_position_value:
                    # Trim down to max_single_position_value
                    excess_value = current_value - max_single_position_value
                    trim_qty = excess_value / price
                    
                    if trim_qty > 0:
                        actions.append({
                            "symbol": symbol,
                            "action": "reduce",
                            "quantity": round(trim_qty, 4),
                            "reason": f"Position value {current_value:.2f} exceeds limit {max_single_position_value:.2f}"
                        })

            return actions

        except Exception as e:
            logger.error(f"Error checking rebalance: {e}")
            return []
