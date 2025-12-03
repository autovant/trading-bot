"""
Shared data models and types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

Mode = Literal["live", "paper", "replay", "backtest"]
Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_market"]


class OrderResponse(BaseModel):
    """Order acknowledgement returned to upstream callers."""

    order_id: str
    client_id: str
    symbol: str
    side: Side
    order_type: str
    quantity: float
    price: Optional[float]
    status: str
    mode: Mode
    timestamp: datetime


class PositionSnapshot(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    percentage: float
    timestamp: datetime


class MarketSnapshot(BaseModel):
    """Current observable market state."""

    symbol: str
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    last_price: float
    last_side: Optional[Side] = None
    last_size: float = 0.0
    funding_rate: float = 0.0
    timestamp: datetime
    order_flow_imbalance: float = 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2.0
        return self.last_price

    @property
    def spread(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return max(self.best_ask - self.best_bid, 0.0)
        return 0.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid <= 0:
            return 0.0
        return (self.spread / mid) * 10_000


class MarketRegime(BaseModel):
    """Market regime classification."""

    regime: str  # 'bullish', 'bearish', 'neutral'
    strength: float  # 0-1
    confidence: float  # 0-1


class TradingSetup(BaseModel):
    """Trading setup classification."""

    direction: str  # 'long', 'short', 'none'
    quality: float  # 0-1
    strength: float  # 0-1


class TradingSignal(BaseModel):
    """Trading signal with metadata."""

    signal_type: str  # 'pullback', 'breakout', 'divergence'
    direction: str  # 'long', 'short'
    strength: float  # 0-1
    confidence: float  # 0-1
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: Optional[datetime] = None
    source: str = "default" # Name of the strategy generating this signal


class ConfidenceScore(BaseModel):
    """Confidence scoring breakdown."""

    regime_score: float
    setup_score: float
    signal_score: float
    penalty_score: float
    total_score: float
