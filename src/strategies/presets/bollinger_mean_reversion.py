import logging
import uuid
from typing import List, Optional

import numpy as np
import pandas as pd

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class BollingerMeanReversionStrategy(IStrategy):
    """
    Mean-reversion strategy using Bollinger Bands and RSI.
    Buy when price touches the lower band AND RSI < oversold threshold.
    Sell when price touches the upper band OR RSI > overbought threshold.
    """

    METADATA = {
        "name": "Bollinger Band Mean Reversion",
        "description": (
            "Buys when price touches the lower Bollinger Band with RSI confirming "
            "oversold conditions. Exits on reversion to the middle band or RSI "
            "overbought signal."
        ),
        "category": "textbook",
        "risk_level": "moderate",
        "recommended_timeframes": ["1h", "4h"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT"],
        "default_params": {
            "bb_period": 20,
            "bb_std": 2.0,
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
        },
    }

    def __init__(
        self,
        symbol: str,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
    ):
        self.symbol = symbol
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.prices: List[float] = []
        self.current_position: Optional[Side] = None

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.prices.append(market_data.close)

        max_needed = max(self.bb_period, self.rsi_period + 1) + 2
        if len(self.prices) > max_needed:
            self.prices.pop(0)

        if len(self.prices) < max_needed:
            return []

        price = market_data.close
        sma, upper, lower = self._bollinger_bands()
        rsi = self._rsi()
        orders: List[Order] = []

        if self.current_position is None:
            if price <= lower and rsi < self.rsi_oversold:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="bb_lower_touch",
                    indicators={"rsi": round(rsi, 1), "sma": round(sma, 2), "upper": round(upper, 2), "lower": round(lower, 2)},
                ))
                self.current_position = Side.BUY
                logger.info(
                    "BB mean-rev LONG %s @%.2f (lower=%.2f, RSI=%.1f)",
                    self.symbol, price, lower, rsi,
                )
        elif self.current_position == Side.BUY:
            if price >= upper or rsi > self.rsi_overbought or price >= sma:
                exit_reason = "bb_upper" if price >= upper else ("rsi_overbought" if rsi > self.rsi_overbought else "bb_middle")
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type=f"exit_long_{exit_reason}",
                    indicators={"rsi": round(rsi, 1), "sma": round(sma, 2), "upper": round(upper, 2), "lower": round(lower, 2)},
                ))
                self.current_position = None
                logger.info(
                    "BB mean-rev EXIT %s @%.2f (upper=%.2f, RSI=%.1f)",
                    self.symbol, price, upper, rsi,
                )

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _bollinger_bands(self) -> tuple:
        series = pd.Series(self.prices)
        sma = series.rolling(window=self.bb_period).mean().iloc[-1]
        std = series.rolling(window=self.bb_period).std(ddof=0).iloc[-1]
        upper = sma + self.bb_std * std
        lower = sma - self.bb_std * std
        return float(sma), float(upper), float(lower)

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
                "strategy_name": "bollinger-mean-reversion",
            },
        )
