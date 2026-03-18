"""Data models for the copy trading bot."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class TradeSide(str, enum.Enum):
    """Trade direction."""

    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, enum.Enum):
    """Lifecycle status of a copied trade."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class SourceTrade(BaseModel):
    """A trade detected on a source wallet."""

    trade_id: str
    wallet: str
    market_id: str
    asset_id: str
    side: TradeSide
    price: float = Field(gt=0)
    size: float = Field(gt=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    market_question: str = ""
    outcome: str = ""


class CopySignal(BaseModel):
    """Signal generated from a source trade after processing."""

    source_trade: SourceTrade
    target_side: TradeSide
    target_price: float = Field(gt=0)
    target_size: float = Field(gt=0)
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CopiedTrade(BaseModel):
    """Record of a trade that was copied (or attempted)."""

    id: Optional[int] = None
    source_trade_id: str
    source_wallet: str
    market_id: str
    asset_id: str
    side: TradeSide
    price: float
    size: float
    status: TradeStatus = TradeStatus.PENDING
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_size: Optional[float] = None
    pnl: Optional[float] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Position(BaseModel):
    """Current open position in a market."""

    market_id: str
    asset_id: str
    side: TradeSide
    size: float = 0.0
    avg_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    market_question: str = ""
    outcome: str = ""

    @property
    def notional(self) -> float:
        """Total notional value of the position."""
        return self.size * self.avg_price


class PortfolioSnapshot(BaseModel):
    """Summary of the portfolio at a point in time."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_value_usdc: float = 0.0
    open_positions: int = 0
    total_exposure_usdc: float = 0.0
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    daily_pnl_usdc: float = 0.0
    consecutive_losses: int = 0
