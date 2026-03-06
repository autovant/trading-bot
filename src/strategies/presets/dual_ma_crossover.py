import logging
import uuid
from typing import List, Optional

import numpy as np

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class DualMACrossoverStrategy(IStrategy):
    """
    Dual EMA crossover strategy with ADX trend-strength filter.
    Golden cross (fast EMA > slow EMA) triggers long entries.
    Death cross triggers short entries. ADX must be above threshold
    to avoid whipsaws in ranging markets.
    """

    METADATA = {
        "name": "Dual MA Crossover",
        "description": (
            "Classic golden/death cross strategy using fast and slow EMAs. "
            "An ADX filter suppresses signals in low-trend environments "
            "to reduce whipsaw losses."
        ),
        "category": "textbook",
        "risk_level": "moderate",
        "recommended_timeframes": ["1h", "4h", "1d"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT"],
        "default_params": {
            "fast_period": 9,
            "slow_period": 21,
            "adx_period": 14,
            "adx_threshold": 25,
        },
    }

    def __init__(
        self,
        symbol: str,
        fast_period: int = 9,
        slow_period: int = 21,
        adx_period: int = 14,
        adx_threshold: float = 25,
    ):
        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.prices: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.fast_ema: Optional[float] = None
        self.slow_ema: Optional[float] = None
        self.prev_fast_ema: Optional[float] = None
        self.prev_slow_ema: Optional[float] = None
        self.current_position: Optional[Side] = None
        self._tick_count = 0

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.prices.append(market_data.close)
        self.highs.append(market_data.high)
        self.lows.append(market_data.low)
        self._tick_count += 1

        buf_size = max(self.slow_period, self.adx_period * 2) + 5
        if len(self.prices) > buf_size:
            self.prices.pop(0)
            self.highs.pop(0)
            self.lows.pop(0)

        if self._tick_count < self.slow_period:
            return []

        # Update EMAs
        self.prev_fast_ema = self.fast_ema
        self.prev_slow_ema = self.slow_ema
        self.fast_ema = self._update_ema(
            market_data.close, self.fast_ema, self.fast_period
        )
        self.slow_ema = self._update_ema(
            market_data.close, self.slow_ema, self.slow_period
        )

        if self.prev_fast_ema is None or self.prev_slow_ema is None:
            return []

        adx = self._adx()
        orders: List[Order] = []

        # Golden cross
        golden = (
            self.prev_fast_ema <= self.prev_slow_ema
            and self.fast_ema > self.slow_ema
        )
        # Death cross
        death = (
            self.prev_fast_ema >= self.prev_slow_ema
            and self.fast_ema < self.slow_ema
        )

        if adx >= self.adx_threshold:
            indicators = {
                "fast_ema": round(self.fast_ema, 2),
                "slow_ema": round(self.slow_ema, 2),
                "adx": round(adx, 1),
            }
            if golden and self.current_position != Side.BUY:
                if self.current_position == Side.SELL:
                    orders.append(self._market_order(
                        Side.BUY, market_data,
                        signal_type="exit_short_ma_cross",
                        indicators=indicators,
                    ))
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="ma_cross_bullish",
                    indicators=indicators,
                ))
                self.current_position = Side.BUY
                logger.info(
                    "MA crossover LONG %s @%.2f (fast=%.2f, slow=%.2f, ADX=%.1f)",
                    self.symbol, market_data.close,
                    self.fast_ema, self.slow_ema, adx,
                )
            elif death and self.current_position != Side.SELL:
                if self.current_position == Side.BUY:
                    orders.append(self._market_order(
                        Side.SELL, market_data,
                        signal_type="exit_long_ma_cross",
                        indicators=indicators,
                    ))
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="ma_cross_bearish",
                    indicators=indicators,
                ))
                self.current_position = Side.SELL
                logger.info(
                    "MA crossover SHORT %s @%.2f (fast=%.2f, slow=%.2f, ADX=%.1f)",
                    self.symbol, market_data.close,
                    self.fast_ema, self.slow_ema, adx,
                )

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _update_ema(
        self, price: float, prev_ema: Optional[float], period: int
    ) -> float:
        alpha = 2.0 / (period + 1)
        if prev_ema is None:
            return float(np.mean(self.prices[-period:]))
        return alpha * price + (1 - alpha) * prev_ema

    def _adx(self) -> float:
        n = self.adx_period
        if len(self.highs) < n + 2:
            return 0.0
        highs = np.array(self.highs[-(n + 1):])
        lows = np.array(self.lows[-(n + 1):])
        closes = np.array(self.prices[-(n + 1):])

        up_move = highs[1:] - highs[:-1]
        down_move = lows[:-1] - lows[1:]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum.reduce([tr1, tr2, tr3])

        atr = float(np.mean(tr))
        if atr == 0:
            return 0.0

        plus_di = 100.0 * float(np.mean(plus_dm)) / atr
        minus_di = 100.0 * float(np.mean(minus_dm)) / atr
        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 0.0
        dx = 100.0 * abs(plus_di - minus_di) / di_sum
        return dx

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
                "strategy_name": "dual-ma-crossover",
            },
        )
