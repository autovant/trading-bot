import logging
import uuid
from typing import List, Optional

import numpy as np

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class MACDDivergenceStrategy(IStrategy):
    """
    MACD divergence strategy.
    Enters on bullish divergence: price making lower lows while MACD histogram
    makes higher lows. Exits on bearish divergence or MACD line/signal crossover.
    """

    METADATA = {
        "name": "MACD Divergence",
        "description": (
            "Detects divergences between price action and the MACD histogram. "
            "Bullish divergence (price lower-low + histogram higher-low) triggers "
            "long entries. Exits on bearish divergence or MACD crossover."
        ),
        "category": "textbook",
        "risk_level": "moderate",
        "recommended_timeframes": ["1h", "4h"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT"],
        "default_params": {
            "fast": 12,
            "slow": 26,
            "signal": 9,
            "divergence_lookback": 5,
        },
    }

    def __init__(
        self,
        symbol: str,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        divergence_lookback: int = 5,
    ):
        self.symbol = symbol
        self.fast_period = fast
        self.slow_period = slow
        self.signal_period = signal
        self.divergence_lookback = divergence_lookback
        self.prices: List[float] = []
        self.fast_ema: Optional[float] = None
        self.slow_ema: Optional[float] = None
        self.signal_ema: Optional[float] = None
        self.macd_history: List[float] = []
        self.histogram_history: List[float] = []
        self.current_position: Optional[Side] = None
        self._tick_count = 0

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.prices.append(market_data.close)
        self._tick_count += 1

        buf_size = self.slow_period + self.signal_period + self.divergence_lookback + 10
        if len(self.prices) > buf_size:
            self.prices.pop(0)

        if self._tick_count < self.slow_period:
            return []

        # Update EMAs
        self.fast_ema = self._update_ema(market_data.close, self.fast_ema, self.fast_period)
        self.slow_ema = self._update_ema(market_data.close, self.slow_ema, self.slow_period)

        macd_line = self.fast_ema - self.slow_ema
        self.macd_history.append(macd_line)

        if len(self.macd_history) > buf_size:
            self.macd_history.pop(0)

        # Signal line (EMA of MACD)
        self.signal_ema = self._update_ema(
            macd_line, self.signal_ema, self.signal_period
        )
        histogram = macd_line - self.signal_ema
        self.histogram_history.append(histogram)

        if len(self.histogram_history) > buf_size:
            self.histogram_history.pop(0)

        if len(self.histogram_history) < self.divergence_lookback:
            return []

        orders: List[Order] = []
        bullish_div = self._bullish_divergence()
        bearish_div = self._bearish_divergence()

        macd_indicators = {"macd": round(macd_line, 4), "signal": round(self.signal_ema, 4), "histogram": round(histogram, 4)}

        if self.current_position is None:
            if bullish_div:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="macd_bullish_divergence",
                    indicators=macd_indicators,
                ))
                self.current_position = Side.BUY
                logger.info(
                    "MACD divergence LONG %s @%.2f (bullish divergence)",
                    self.symbol, market_data.close,
                )
        elif self.current_position == Side.BUY:
            # Exit on bearish divergence or MACD crossing below signal
            if bearish_div or (len(self.macd_history) >= 2
                               and self.macd_history[-2] >= 0
                               and self.macd_history[-1] < 0):
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="exit_long_macd",
                    indicators={**macd_indicators, "bearish_divergence": bearish_div},
                ))
                self.current_position = None
                logger.info(
                    "MACD divergence EXIT %s @%.2f (bearish_div=%s)",
                    self.symbol, market_data.close, bearish_div,
                )
        elif self.current_position == Side.SELL:
            if bullish_div or (len(self.macd_history) >= 2
                               and self.macd_history[-2] <= 0
                               and self.macd_history[-1] > 0):
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="exit_short_macd",
                    indicators={**macd_indicators, "bullish_divergence": bullish_div},
                ))
                self.current_position = None

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _update_ema(
        self, value: float, prev_ema: Optional[float], period: int
    ) -> float:
        alpha = 2.0 / (period + 1)
        if prev_ema is None:
            return float(np.mean(self.prices[-period:]))
        return alpha * value + (1 - alpha) * prev_ema

    def _bullish_divergence(self) -> bool:
        """Price making lower lows, histogram making higher lows."""
        lb = self.divergence_lookback
        if len(self.prices) < lb or len(self.histogram_history) < lb:
            return False
        recent_prices = self.prices[-lb:]
        recent_hist = self.histogram_history[-lb:]
        price_lower_low = recent_prices[-1] < min(recent_prices[:-1])
        hist_higher_low = recent_hist[-1] > min(recent_hist[:-1])
        return price_lower_low and hist_higher_low

    def _bearish_divergence(self) -> bool:
        """Price making higher highs, histogram making lower highs."""
        lb = self.divergence_lookback
        if len(self.prices) < lb or len(self.histogram_history) < lb:
            return False
        recent_prices = self.prices[-lb:]
        recent_hist = self.histogram_history[-lb:]
        price_higher_high = recent_prices[-1] > max(recent_prices[:-1])
        hist_lower_high = recent_hist[-1] < max(recent_hist[:-1])
        return price_higher_high and hist_lower_high

    def _market_order(
        self,
        side: Side,
        market_data: MarketData,
        signal_type: str = "",
        indicators: Optional[dict] = None,
    ) -> Order:
        return Order(
            id=str(uuid.uuid4()),
            symbol=self.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=market_data.close,
            metadata={
                "tick_price": market_data.close,
                "signal_type": signal_type,
                "entry_indicators": indicators or {},
                "strategy_name": "macd-divergence",
            },
        )
