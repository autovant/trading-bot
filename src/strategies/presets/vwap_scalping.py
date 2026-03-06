import logging
import uuid
from datetime import date
from typing import List, Optional

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class VWAPScalpingStrategy(IStrategy):
    """
    Intraday scalping strategy around the VWAP line.
    Buy below VWAP when a bullish reversal candle appears.
    Sell above VWAP when a bearish reversal candle appears.
    VWAP resets daily.
    """

    METADATA = {
        "name": "VWAP Scalping",
        "description": (
            "Scalps around the Volume-Weighted Average Price, entering on reversal "
            "candle patterns when price deviates from VWAP by a configurable amount. "
            "VWAP resets each trading day."
        ),
        "category": "textbook",
        "risk_level": "aggressive",
        "recommended_timeframes": ["1m", "5m", "15m"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "default_params": {
            "vwap_deviation": 0.005,
            "volume_threshold": 2.0,
        },
    }

    def __init__(
        self,
        symbol: str,
        vwap_deviation: float = 0.005,
        volume_threshold: float = 2.0,
    ):
        self.symbol = symbol
        self.vwap_deviation = vwap_deviation
        self.volume_threshold = volume_threshold
        self.cum_pv: float = 0.0
        self.cum_volume: float = 0.0
        self.current_date: Optional[date] = None
        self.prev_open: Optional[float] = None
        self.prev_close: Optional[float] = None
        self.volumes: List[float] = []
        self.current_position: Optional[Side] = None

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        tick_date = market_data.timestamp.date()
        if self.current_date != tick_date:
            self.cum_pv = 0.0
            self.cum_volume = 0.0
            self.current_date = tick_date

        typical_price = (market_data.high + market_data.low + market_data.close) / 3.0
        self.cum_pv += typical_price * market_data.volume
        self.cum_volume += market_data.volume
        self.volumes.append(market_data.volume)

        if len(self.volumes) > 50:
            self.volumes.pop(0)

        orders: List[Order] = []

        if self.cum_volume == 0 or self.prev_close is None or self.prev_open is None:
            self.prev_open = market_data.open
            self.prev_close = market_data.close
            return []

        vwap = self.cum_pv / self.cum_volume
        price = market_data.close
        deviation = (price - vwap) / vwap if vwap != 0 else 0.0
        avg_vol = sum(self.volumes[:-1]) / len(self.volumes[:-1]) if len(self.volumes) > 1 else 0.0
        volume_ok = avg_vol > 0 and market_data.volume > self.volume_threshold * avg_vol

        bullish_reversal = (
            self.prev_close < self.prev_open  # prior bearish candle
            and market_data.close > market_data.open  # current bullish candle
        )
        bearish_reversal = (
            self.prev_close > self.prev_open  # prior bullish candle
            and market_data.close < market_data.open  # current bearish candle
        )

        if self.current_position is None:
            if deviation < -self.vwap_deviation and bullish_reversal and volume_ok:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="vwap_long",
                    indicators={"vwap": round(vwap, 2), "deviation": round(deviation, 4), "volume": round(market_data.volume, 2), "avg_volume": round(avg_vol, 2)},
                ))
                self.current_position = Side.BUY
                logger.info(
                    "VWAP scalp LONG %s @%.2f (VWAP=%.2f, dev=%.4f)",
                    self.symbol, price, vwap, deviation,
                )
            elif deviation > self.vwap_deviation and bearish_reversal and volume_ok:
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="vwap_short",
                    indicators={"vwap": round(vwap, 2), "deviation": round(deviation, 4), "volume": round(market_data.volume, 2), "avg_volume": round(avg_vol, 2)},
                ))
                self.current_position = Side.SELL
                logger.info(
                    "VWAP scalp SHORT %s @%.2f (VWAP=%.2f, dev=%.4f)",
                    self.symbol, price, vwap, deviation,
                )
        elif self.current_position == Side.BUY and price >= vwap:
            orders.append(self._market_order(
                Side.SELL, market_data,
                signal_type="exit_long_vwap_cross",
                indicators={"vwap": round(vwap, 2), "price": round(price, 2)},
            ))
            self.current_position = None
            logger.info("VWAP scalp EXIT LONG %s @%.2f (VWAP=%.2f)",
                        self.symbol, price, vwap)
        elif self.current_position == Side.SELL and price <= vwap:
            orders.append(self._market_order(
                Side.BUY, market_data,
                signal_type="exit_short_vwap_cross",
                indicators={"vwap": round(vwap, 2), "price": round(price, 2)},
            ))
            self.current_position = None
            logger.info("VWAP scalp EXIT SHORT %s @%.2f (VWAP=%.2f)",
                        self.symbol, price, vwap)

        self.prev_open = market_data.open
        self.prev_close = market_data.close
        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

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
                "strategy_name": "vwap-scalping",
            },
        )
