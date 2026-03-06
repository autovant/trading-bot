import logging
import uuid
from typing import List, Optional

import numpy as np
import pandas as pd

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class BreakoutVolumeStrategy(IStrategy):
    """
    Breakout strategy entering when price breaks above/below the lookback
    high/low with a volume surge and ATR volatility filter.
    """

    METADATA = {
        "name": "Breakout with Volume Confirmation",
        "description": (
            "Enters when price breaks above the lookback-period high or below the "
            "lookback-period low, confirmed by volume exceeding a multiplier of the "
            "average. An ATR filter ensures sufficient volatility for follow-through."
        ),
        "category": "textbook",
        "risk_level": "aggressive",
        "recommended_timeframes": ["15m", "1h", "4h"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "default_params": {
            "lookback": 20,
            "volume_multiplier": 2.0,
            "atr_period": 14,
        },
    }

    def __init__(
        self,
        symbol: str,
        lookback: int = 20,
        volume_multiplier: float = 2.0,
        atr_period: int = 14,
    ):
        self.symbol = symbol
        self.lookback = lookback
        self.volume_multiplier = volume_multiplier
        self.atr_period = atr_period
        self.prices: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.volumes: List[float] = []
        self.current_position: Optional[Side] = None
        self.entry_price: Optional[float] = None

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.prices.append(market_data.close)
        self.highs.append(market_data.high)
        self.lows.append(market_data.low)
        self.volumes.append(market_data.volume)

        buf_size = max(self.lookback, self.atr_period) + 5
        if len(self.prices) > buf_size:
            self.prices.pop(0)
            self.highs.pop(0)
            self.lows.pop(0)
            self.volumes.pop(0)

        if len(self.prices) < self.lookback + 1:
            return []

        price = market_data.close
        lookback_highs = self.highs[-(self.lookback + 1):-1]
        lookback_lows = self.lows[-(self.lookback + 1):-1]
        resistance = max(lookback_highs)
        support = min(lookback_lows)

        avg_volume = float(np.mean(self.volumes[:-1]))
        volume_surge = avg_volume > 0 and market_data.volume > self.volume_multiplier * avg_volume
        atr = self._atr()

        orders: List[Order] = []

        if self.current_position is None and volume_surge and atr > 0:
            if price > resistance:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="breakout_long",
                    indicators={"resistance": round(resistance, 2), "atr": round(atr, 2), "volume": round(market_data.volume, 2), "avg_volume": round(avg_volume, 2)},
                ))
                self.current_position = Side.BUY
                self.entry_price = price
                logger.info(
                    "Breakout LONG %s @%.2f (resistance=%.2f, ATR=%.2f, vol_surge=%s)",
                    self.symbol, price, resistance, atr, volume_surge,
                )
            elif price < support:
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="breakout_short",
                    indicators={"support": round(support, 2), "atr": round(atr, 2), "volume": round(market_data.volume, 2), "avg_volume": round(avg_volume, 2)},
                ))
                self.current_position = Side.SELL
                self.entry_price = price
                logger.info(
                    "Breakout SHORT %s @%.2f (support=%.2f, ATR=%.2f, vol_surge=%s)",
                    self.symbol, price, support, atr, volume_surge,
                )
        elif self.current_position is not None and self.entry_price is not None:
            # Exit on ATR-based stop or reversion
            if self.current_position == Side.BUY and price < self.entry_price - 2 * atr:
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="exit_long_breakout_stop",
                    indicators={"atr": round(atr, 2), "entry_price": round(self.entry_price, 2)},
                ))
                self.current_position = None
                self.entry_price = None
                logger.info("Breakout STOP EXIT LONG %s @%.2f", self.symbol, price)
            elif self.current_position == Side.SELL and price > self.entry_price + 2 * atr:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="exit_short_breakout_stop",
                    indicators={"atr": round(atr, 2), "entry_price": round(self.entry_price, 2)},
                ))
                self.current_position = None
                self.entry_price = None
                logger.info("Breakout STOP EXIT SHORT %s @%.2f", self.symbol, price)

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _atr(self) -> float:
        n = self.atr_period
        if len(self.prices) < n + 1:
            return 0.0
        highs = np.array(self.highs[-(n + 1):])
        lows = np.array(self.lows[-(n + 1):])
        closes = np.array(self.prices[-(n + 1):])
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum.reduce([tr1, tr2, tr3])
        return float(pd.Series(tr).rolling(n).mean().iloc[-1])

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
                "strategy_name": "breakout-volume",
            },
        )
