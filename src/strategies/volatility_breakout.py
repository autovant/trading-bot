import logging
import uuid
from typing import List, Optional

import numpy as np
import pandas as pd

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class VolatilityBreakoutStrategy(IStrategy):
    """
    Bollinger/ATR breakout with simple stateful position management.
    """

    def __init__(self, symbol: str, lookback: int = 20, k: float = 2.0, atr_window: int = 14):
        self.symbol = symbol
        self.lookback = lookback
        self.k = k
        self.atr_window = atr_window
        self.prices: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.current_position: Optional[Side] = None

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.prices.append(market_data.close)
        self.highs.append(market_data.high)
        self.lows.append(market_data.low)

        if len(self.prices) > max(self.lookback + 2, self.atr_window + 2):
            self.prices.pop(0)
            self.highs.pop(0)
            self.lows.pop(0)

        if len(self.prices) < self.lookback:
            return []

        series = pd.Series(self.prices)
        sma = series.rolling(window=self.lookback).mean().iloc[-1]
        std = series.rolling(window=self.lookback).std(ddof=0).iloc[-1]
        upper_band = sma + self.k * std
        lower_band = sma - self.k * std

        atr = self._atr()
        price = market_data.close
        orders: List[Order] = []

        if self.current_position is None:
            if price > upper_band:
                orders.append(self._market_order(Side.BUY, market_data))
                self.current_position = Side.BUY
                logger.info("Vol breakout LONG %s @%.2f (band %.2f)", self.symbol, price, upper_band)
            elif price < lower_band:
                orders.append(self._market_order(Side.SELL, market_data))
                self.current_position = Side.SELL
                logger.info("Vol breakout SHORT %s @%.2f (band %.2f)", self.symbol, price, lower_band)
        else:
            # exit on mean reversion or ATR stop
            mid = sma
            if self.current_position == Side.BUY and (price < mid or price < (upper_band - 1.5 * atr)):
                orders.append(self._market_order(Side.SELL, market_data))
                self.current_position = None
            elif self.current_position == Side.SELL and (price > mid or price > (lower_band + 1.5 * atr)):
                orders.append(self._market_order(Side.BUY, market_data))
                self.current_position = None

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _atr(self) -> float:
        if len(self.prices) < self.atr_window + 1:
            return 0.0
        highs = np.array(self.highs[-self.atr_window - 1 :])
        lows = np.array(self.lows[-self.atr_window - 1 :])
        closes = np.array(self.prices[-self.atr_window - 1 :])
        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum.reduce([tr1, tr2, tr3])
        return float(pd.Series(tr).rolling(self.atr_window).mean().iloc[-1])

    def _market_order(self, side: Side, market_data: MarketData) -> Order:
        return Order(
            id=str(uuid.uuid4()),
            symbol=self.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=market_data.close,
            metadata={"tick_price": market_data.close},
        )
