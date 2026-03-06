import logging
import uuid
from typing import List, Optional

import numpy as np

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class RSIMomentumStrategy(IStrategy):
    """
    Momentum strategy using RSI crossovers with volume confirmation.
    Enter long when RSI crosses above oversold with volume surge.
    Enter short when RSI crosses below overbought with volume surge.
    """

    METADATA = {
        "name": "RSI Momentum",
        "description": (
            "Enters long when RSI crosses above the oversold threshold from below "
            "with volume exceeding the average by a configurable multiplier. "
            "Enters short on the inverse overbought crossover."
        ),
        "category": "textbook",
        "risk_level": "moderate",
        "recommended_timeframes": ["15m", "1h"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "default_params": {
            "rsi_period": 14,
            "volume_threshold": 1.5,
            "overbought": 70,
            "oversold": 30,
        },
    }

    def __init__(
        self,
        symbol: str,
        rsi_period: int = 14,
        volume_threshold: float = 1.5,
        overbought: float = 70,
        oversold: float = 30,
    ):
        self.symbol = symbol
        self.rsi_period = rsi_period
        self.volume_threshold = volume_threshold
        self.overbought = overbought
        self.oversold = oversold
        self.prices: List[float] = []
        self.volumes: List[float] = []
        self.prev_rsi: Optional[float] = None
        self.current_position: Optional[Side] = None

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.prices.append(market_data.close)
        self.volumes.append(market_data.volume)

        max_needed = self.rsi_period + 2
        vol_lookback = max(20, self.rsi_period)
        buf_size = max(max_needed, vol_lookback) + 2
        if len(self.prices) > buf_size:
            self.prices.pop(0)
            self.volumes.pop(0)

        if len(self.prices) < max_needed:
            return []

        rsi = self._rsi()
        avg_volume = float(np.mean(self.volumes[:-1])) if len(self.volumes) > 1 else 0.0
        volume_ok = avg_volume > 0 and market_data.volume > self.volume_threshold * avg_volume
        orders: List[Order] = []

        if self.prev_rsi is not None and self.current_position is None:
            # Bullish crossover: RSI crosses above oversold
            if self.prev_rsi < self.oversold and rsi >= self.oversold and volume_ok:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="rsi_momentum_long",
                    indicators={"rsi": round(rsi, 1), "prev_rsi": round(self.prev_rsi, 1), "volume": round(market_data.volume, 2), "avg_volume": round(avg_volume, 2)},
                ))
                self.current_position = Side.BUY
                logger.info(
                    "RSI momentum LONG %s @%.2f (RSI %.1f->%.1f, vol_ok=%s)",
                    self.symbol, market_data.close, self.prev_rsi, rsi, volume_ok,
                )
            # Bearish crossover: RSI crosses below overbought
            elif self.prev_rsi > self.overbought and rsi <= self.overbought and volume_ok:
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="rsi_momentum_short",
                    indicators={"rsi": round(rsi, 1), "prev_rsi": round(self.prev_rsi, 1), "volume": round(market_data.volume, 2), "avg_volume": round(avg_volume, 2)},
                ))
                self.current_position = Side.SELL
                logger.info(
                    "RSI momentum SHORT %s @%.2f (RSI %.1f->%.1f, vol_ok=%s)",
                    self.symbol, market_data.close, self.prev_rsi, rsi, volume_ok,
                )
        elif self.current_position == Side.BUY and rsi > self.overbought:
            orders.append(self._market_order(
                Side.SELL, market_data,
                signal_type="exit_long_rsi_overbought",
                indicators={"rsi": round(rsi, 1)},
            ))
            self.current_position = None
            logger.info("RSI momentum EXIT LONG %s @%.2f (RSI=%.1f)",
                        self.symbol, market_data.close, rsi)
        elif self.current_position == Side.SELL and rsi < self.oversold:
            orders.append(self._market_order(
                Side.BUY, market_data,
                signal_type="exit_short_rsi_oversold",
                indicators={"rsi": round(rsi, 1)},
            ))
            self.current_position = None
            logger.info("RSI momentum EXIT SHORT %s @%.2f (RSI=%.1f)",
                        self.symbol, market_data.close, rsi)

        self.prev_rsi = rsi
        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _rsi(self) -> float:
        deltas = np.diff(self.prices[-(self.rsi_period + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

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
                "strategy_name": "rsi-momentum",
            },
        )
