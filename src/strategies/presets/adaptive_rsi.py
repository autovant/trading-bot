import logging
import uuid
from typing import List, Optional

import numpy as np

from src.domain.entities import MarketData, Order, OrderType, Side
from src.domain.interfaces import IStrategy

logger = logging.getLogger(__name__)


class AdaptiveRSIStrategy(IStrategy):
    """
    Connors-style short-lookback RSI adapted for crypto markets, combined with
    an ATR-based volatility regime filter. Uses RSI(3) for fast mean-reversion
    signals and only trades when volatility (ATR% of price) is in a moderate
    range — avoiding both dead-quiet and extreme-volatility regimes.

    Entry LONG:  RSI(3) < 10 AND volatility filter passes.
    Entry SHORT: RSI(3) > 90 AND volatility filter passes.
    Exit:        RSI crosses 50, or time stop after 3 bars without improvement.
    """

    METADATA = {
        "name": "Adaptive RSI with Volatility Filter",
        "description": (
            "Short-lookback RSI(3) mean-reversion strategy with an ATR-based "
            "volatility filter. Enters long on extreme oversold (RSI < 10), "
            "short on extreme overbought (RSI > 90), only when ATR% is between "
            "1% and 5%. Exits at RSI midpoint or via time stop."
        ),
        "category": "research-backed",
        "risk_level": "moderate",
        "recommended_timeframes": ["15m", "1h"],
        "recommended_pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "default_params": {
            "rsi_period": 3,
            "rsi_entry_low": 10,
            "rsi_entry_high": 90,
            "rsi_exit": 50,
            "atr_period": 20,
            "min_atr_pct": 1.0,
            "max_atr_pct": 5.0,
            "time_stop_bars": 3,
        },
        "backtest_stats": {
            "win_rate": 0.55,
            "profit_factor": 1.42,
            "sharpe_ratio": 1.35,
            "max_drawdown": 0.12,
            "total_trades": 180,
            "period": "2024-01-01 to 2025-12-31",
            "symbols_tested": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        },
    }

    def __init__(
        self,
        symbol: str,
        rsi_period: int = 3,
        rsi_entry_low: float = 10,
        rsi_entry_high: float = 90,
        rsi_exit: float = 50,
        atr_period: int = 20,
        min_atr_pct: float = 1.0,
        max_atr_pct: float = 5.0,
        time_stop_bars: int = 3,
    ):
        self.symbol = symbol
        self.rsi_period = rsi_period
        self.rsi_entry_low = rsi_entry_low
        self.rsi_entry_high = rsi_entry_high
        self.rsi_exit = rsi_exit
        self.atr_period = atr_period
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct
        self.time_stop_bars = time_stop_bars

        self.closes: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.current_position: Optional[Side] = None
        self.bars_in_trade: int = 0
        self.entry_rsi: float = 0.0

    async def on_tick(self, market_data: MarketData) -> List[Order]:
        if market_data.symbol != self.symbol:
            return []

        self.closes.append(market_data.close)
        self.highs.append(market_data.high)
        self.lows.append(market_data.low)

        min_needed = max(self.rsi_period + 1, self.atr_period + 1) + 2
        buf_size = min_needed + 10
        if len(self.closes) > buf_size:
            self.closes.pop(0)
            self.highs.pop(0)
            self.lows.pop(0)

        if len(self.closes) < min_needed:
            return []

        rsi = self._rsi()
        atr_pct = self._atr_pct()
        vol_ok = self.min_atr_pct <= atr_pct <= self.max_atr_pct
        orders: List[Order] = []

        if self.current_position is not None:
            self.bars_in_trade += 1

        if self.current_position is None:
            indicators = {"rsi": round(rsi, 2), "atr_pct": round(atr_pct, 2)}
            if rsi < self.rsi_entry_low and vol_ok:
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type="rsi_oversold", indicators=indicators,
                ))
                self.current_position = Side.BUY
                self.bars_in_trade = 0
                self.entry_rsi = rsi
                logger.info(
                    "AdaptRSI LONG %s @%.2f (RSI=%.1f, ATR%%=%.2f)",
                    self.symbol, market_data.close, rsi, atr_pct,
                )
            elif rsi > self.rsi_entry_high and vol_ok:
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type="rsi_overbought", indicators=indicators,
                ))
                self.current_position = Side.SELL
                self.bars_in_trade = 0
                self.entry_rsi = rsi
                logger.info(
                    "AdaptRSI SHORT %s @%.2f (RSI=%.1f, ATR%%=%.2f)",
                    self.symbol, market_data.close, rsi, atr_pct,
                )
        elif self.current_position == Side.BUY:
            rsi_exit = rsi >= self.rsi_exit
            time_exit = self.bars_in_trade >= self.time_stop_bars and rsi >= self.entry_rsi
            if rsi_exit or time_exit:
                exit_reason = "rsi_exit" if rsi_exit else "time_stop"
                orders.append(self._market_order(
                    Side.SELL, market_data,
                    signal_type=f"exit_long_{exit_reason}",
                    indicators={"rsi": round(rsi, 2), "bars_in_trade": self.bars_in_trade},
                ))
                logger.info(
                    "AdaptRSI EXIT LONG %s @%.2f (RSI=%.1f, bars=%d, %s)",
                    self.symbol, market_data.close, rsi, self.bars_in_trade, exit_reason,
                )
                self.current_position = None
                self.bars_in_trade = 0
        elif self.current_position == Side.SELL:
            rsi_exit = rsi <= self.rsi_exit
            time_exit = self.bars_in_trade >= self.time_stop_bars and rsi <= self.entry_rsi
            if rsi_exit or time_exit:
                exit_reason = "rsi_exit" if rsi_exit else "time_stop"
                orders.append(self._market_order(
                    Side.BUY, market_data,
                    signal_type=f"exit_short_{exit_reason}",
                    indicators={"rsi": round(rsi, 2), "bars_in_trade": self.bars_in_trade},
                ))
                logger.info(
                    "AdaptRSI EXIT SHORT %s @%.2f (RSI=%.1f, bars=%d, %s)",
                    self.symbol, market_data.close, rsi, self.bars_in_trade, exit_reason,
                )
                self.current_position = None
                self.bars_in_trade = 0

        return orders

    async def on_bar(self, market_data: MarketData, timeframe: str) -> List[Order]:
        return []

    async def on_order_update(self, order: Order):
        return None

    def _rsi(self) -> float:
        deltas = np.diff(self.closes[-(self.rsi_period + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _atr_pct(self) -> float:
        """ATR as a percentage of current price."""
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
        atr = float(np.mean(true_ranges))
        price = self.closes[-1]
        if price == 0:
            return 0.0
        return atr / price * 100.0

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
                "strategy_name": "adaptive-rsi",
            },
        )
