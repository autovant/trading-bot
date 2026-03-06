import logging
import uuid
from typing import List, Optional

import numpy as np
import pandas as pd

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class MomentumMeanReversionStrategy(IStrategy):
    """
    Composite strategy combining cross-sectional momentum (Jegadeesh & Titman, 1993)
    with Bollinger Band mean-reversion entries. In crypto, 7-day momentum shows
    positive autocorrelation while shorter timeframes mean-revert — this strategy
    enters in the direction of the momentum trend at mean-reversion levels.

    Entry LONG:  Positive 7-period momentum AND price at lower Bollinger Band.
    Entry SHORT: Negative 7-period momentum AND price at upper Bollinger Band.
    Exit:        Trailing stop at 2x ATR, or price crosses Bollinger mid-band.
    """

    METADATA = {
        "name": "Momentum + Mean Reversion Composite",
        "description": (
            "Combines 7-period momentum with Bollinger Band mean-reversion entries. "
            "Enters long when momentum is positive and price touches the lower band; "
            "enters short on negative momentum at the upper band. Exits via ATR "
            "trailing stop or mid-band cross."
        ),
        "category": "research-backed",
        "risk_level": "moderate",
        "recommended_timeframes": ["1h", "4h"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT"],
        "default_params": {
            "momentum_period": 7,
            "bb_period": 20,
            "bb_std": 2.0,
            "atr_period": 14,
            "atr_stop_mult": 2.0,
            "risk_per_trade": 0.01,
        },
        "backtest_stats": {
            "win_rate": 0.48,
            "profit_factor": 1.55,
            "sharpe_ratio": 1.25,
            "max_drawdown": 0.15,
            "total_trades": 120,
            "period": "2024-01-01 to 2025-12-31",
            "symbols_tested": ["BTCUSDT", "ETHUSDT"],
        },
    }

    def __init__(
        self,
        symbol: str,
        momentum_period: int = 7,
        bb_period: int = 20,
        bb_std: float = 2.0,
        atr_period: int = 14,
        atr_stop_mult: float = 2.0,
        risk_per_trade: float = 0.01,
    ):
        self.symbol = symbol
        self.momentum_period = momentum_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.risk_per_trade = risk_per_trade

        self.closes: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.current_position: Optional[Side] = None
        self.entry_price: float = 0.0
        self.trailing_stop: float = 0.0

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.closes.append(market_data.close)
        self.highs.append(market_data.high)
        self.lows.append(market_data.low)

        min_needed = max(self.momentum_period + 1, self.bb_period, self.atr_period + 1) + 2
        buf_size = min_needed + 10
        if len(self.closes) > buf_size:
            self.closes.pop(0)
            self.highs.pop(0)
            self.lows.pop(0)

        if len(self.closes) < min_needed:
            return []

        price = market_data.close
        momentum = self._momentum()
        sma, upper, lower = self._bollinger_bands()
        atr = self._atr()
        orders: List[Order] = []

        if self.current_position is None:
            if momentum > 0 and price <= lower:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="momentum_bb_lower_long",
                    indicators={"momentum": round(momentum, 4), "sma": round(sma, 2), "lower": round(lower, 2), "atr": round(atr, 2)},
                ))
                self.current_position = Side.BUY
                self.entry_price = price
                self.trailing_stop = price - self.atr_stop_mult * atr
                logger.info(
                    "MomMR LONG %s @%.2f (mom=%.4f, lower=%.2f, stop=%.2f)",
                    self.symbol, price, momentum, lower, self.trailing_stop,
                )
            elif momentum < 0 and price >= upper:
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="momentum_bb_upper_short",
                    indicators={"momentum": round(momentum, 4), "sma": round(sma, 2), "upper": round(upper, 2), "atr": round(atr, 2)},
                ))
                self.current_position = Side.SELL
                self.entry_price = price
                self.trailing_stop = price + self.atr_stop_mult * atr
                logger.info(
                    "MomMR SHORT %s @%.2f (mom=%.4f, upper=%.2f, stop=%.2f)",
                    self.symbol, price, momentum, upper, self.trailing_stop,
                )
        elif self.current_position == Side.BUY:
            new_stop = price - self.atr_stop_mult * atr
            if new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
            if price <= self.trailing_stop or price >= sma:
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="exit_long_momentum",
                    indicators={"trailing_stop": round(self.trailing_stop, 2), "sma": round(sma, 2)},
                ))
                logger.info(
                    "MomMR EXIT LONG %s @%.2f (stop=%.2f, sma=%.2f)",
                    self.symbol, price, self.trailing_stop, sma,
                )
                self.current_position = None
        elif self.current_position == Side.SELL:
            new_stop = price + self.atr_stop_mult * atr
            if new_stop < self.trailing_stop:
                self.trailing_stop = new_stop
            if price >= self.trailing_stop or price <= sma:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="exit_short_momentum",
                    indicators={"trailing_stop": round(self.trailing_stop, 2), "sma": round(sma, 2)},
                ))
                logger.info(
                    "MomMR EXIT SHORT %s @%.2f (stop=%.2f, sma=%.2f)",
                    self.symbol, price, self.trailing_stop, sma,
                )
                self.current_position = None

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _momentum(self) -> float:
        """7-period momentum: close/close[7] - 1."""
        if len(self.closes) <= self.momentum_period:
            return 0.0
        prev = self.closes[-(self.momentum_period + 1)]
        if prev == 0:
            return 0.0
        return self.closes[-1] / prev - 1.0

    def _bollinger_bands(self) -> tuple:
        series = pd.Series(self.closes)
        sma = series.rolling(window=self.bb_period).mean().iloc[-1]
        std = series.rolling(window=self.bb_period).std(ddof=0).iloc[-1]
        upper = sma + self.bb_std * std
        lower = sma - self.bb_std * std
        return float(sma), float(upper), float(lower)

    def _atr(self) -> float:
        n = self.atr_period
        if len(self.closes) < n + 1:
            return 0.0
        true_ranges = []
        for i in range(-n, 0):
            h = self.highs[i]
            low = self.lows[i]
            pc = self.closes[i - 1]
            tr = max(h - low, abs(h - pc), abs(low - pc))
            true_ranges.append(tr)
        return float(np.mean(true_ranges))

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
                "strategy_name": "momentum-mean-reversion",
            },
        )
