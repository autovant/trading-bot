import logging
import uuid
from collections import deque
from typing import Deque, Dict, List, Tuple

import numpy as np

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class StatisticalArbitrageStrategy(IStrategy):
    """
    Simple mean-reversion pair strategy.
    Goes long spread when price_a underperforms price_b beyond threshold and vice versa.
    """

    def __init__(
        self,
        symbol_pair: Tuple[str, str],
        z_score_threshold: float = 2.0,
        lookback: int = 120,
    ):
        self.symbol_pair = symbol_pair
        self.z_score_threshold = z_score_threshold
        self.lookback = lookback
        self.prices: Dict[str, Deque[float]] = {
            s: deque(maxlen=lookback) for s in symbol_pair
        }
        self.spread_state: int = (
            0  # 0 = flat, 1 = long spread (long A short B), -1 = short spread
        )

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol not in self.symbol_pair:
            return []

        self.prices[market_data.symbol].append(market_data.close)
        if any(len(self.prices[s]) < self.lookback for s in self.symbol_pair):
            return []

        a, b = self.symbol_pair
        spread = self._spread_series()
        z_score = self._zscore(spread)

        orders: List[Order] = []
        if self.spread_state == 0:
            if z_score > self.z_score_threshold:
                # Short A, Long B
                orders.extend(
                    self._build_pair_orders(
                        short_symbol=a, long_symbol=b, qty=1.0, price=market_data.close
                    )
                )
                self.spread_state = -1
                logger.info("StatArb opening SHORT spread %s/%s z=%.2f", a, b, z_score)
            elif z_score < -self.z_score_threshold:
                # Long A, Short B
                orders.extend(
                    self._build_pair_orders(
                        short_symbol=b, long_symbol=a, qty=1.0, price=market_data.close
                    )
                )
                self.spread_state = 1
                logger.info("StatArb opening LONG spread %s/%s z=%.2f", a, b, z_score)
        else:
            if abs(z_score) < 0.5:
                # Exit both legs
                orders.extend(self._close_spread())
                logger.info("StatArb closing spread %s/%s z=%.2f", a, b, z_score)

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _spread_series(self) -> np.ndarray:
        a, b = self.symbol_pair
        return np.log(np.array(self.prices[a])) - np.log(np.array(self.prices[b]))

    def _zscore(self, series: np.ndarray) -> float:
        if series.size < 2:
            return 0.0
        mean = series.mean()
        std = series.std()
        return float((series[-1] - mean) / std) if std > 0 else 0.0

    def _build_pair_orders(
        self, short_symbol: str, long_symbol: str, qty: float, price: float
    ) -> List[Order]:
        return [
            Order(
                id=str(uuid.uuid4()),
                symbol=long_symbol,
                side=Side.BUY,
                order_type=OrderType.MARKET,
                quantity=qty,
                price=price,
                metadata={"tick_price": price},
            ),
            Order(
                id=str(uuid.uuid4()),
                symbol=short_symbol,
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=qty,
                price=price,
                metadata={"tick_price": price},
            ),
        ]

    def _close_spread(self) -> List[Order]:
        orders: List[Order] = []
        a, b = self.symbol_pair
        if self.spread_state == 1:
            # Long A / Short B -> close by selling A, buying B
            orders.extend(
                self._build_pair_orders(
                    short_symbol=a, long_symbol=b, qty=1.0, price=self.prices[a][-1]
                )
            )
        elif self.spread_state == -1:
            # Short A / Long B -> close by buying A, selling B
            orders.extend(
                self._build_pair_orders(
                    short_symbol=b, long_symbol=a, qty=1.0, price=self.prices[b][-1]
                )
            )
        self.spread_state = 0
        return orders
