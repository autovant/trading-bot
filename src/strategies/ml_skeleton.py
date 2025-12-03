import logging
import uuid
from collections import deque
from typing import Deque, List, Optional

import numpy as np

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class MLStrategy(IStrategy):
    """
    Skeleton for ML-driven signal generation.
    Provides a simple momentum fallback when model is absent.
    """

    def __init__(self, model_path: str, lookback: int = 30, threshold: float = 0.55):
        self.model_path = model_path
        self.model = None  # Integrate XGBoost/LSTM model here
        self.lookback = lookback
        self.threshold = threshold
        self.window: Deque[float] = deque(maxlen=lookback)
        self.current_position: Optional[Side] = None

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        self.window.append(market_data.close)
        if len(self.window) < self.lookback:
            return []

        features = self._extract_features()
        score = self._predict(features)
        orders: List[Order] = []

        if score > self.threshold and self.current_position != Side.BUY:
            orders.append(self._order(Side.BUY, market_data))
            self.current_position = Side.BUY
            logger.info("MLStrategy momentum long score=%.2f", score)
        elif score < (1 - self.threshold) and self.current_position != Side.SELL:
            orders.append(self._order(Side.SELL, market_data))
            self.current_position = Side.SELL
            logger.info("MLStrategy momentum short score=%.2f", score)
        elif 0.48 < score < 0.52 and self.current_position is not None:
            # Flat when model is uncertain
            exit_side = Side.SELL if self.current_position == Side.BUY else Side.BUY
            orders.append(self._order(exit_side, market_data))
            self.current_position = None

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _extract_features(self) -> np.ndarray:
        prices = np.array(self.window, dtype=float)
        returns = np.diff(prices) / prices[:-1]
        momentum = returns[-5:].sum()
        vol = returns[-10:].std() if returns.size >= 10 else 0.0
        return np.array([returns[-1], momentum, vol])

    def _predict(self, features: np.ndarray) -> float:
        if self.model:
            # Replace with model inference
            return float(self.model.predict_proba(features.reshape(1, -1))[0][1])
        # fallback heuristic: normalized momentum signal mapped to [0,1]
        score = 0.5 + float(features[1]) * 5
        return max(0.0, min(1.0, score))

    def _order(self, side: Side, market_data: MarketData) -> Order:
        return Order(
            id=str(uuid.uuid4()),
            symbol=market_data.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=market_data.close,
            metadata={"tick_price": market_data.close},
        )
