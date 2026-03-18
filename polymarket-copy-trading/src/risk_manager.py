"""Risk manager — enforces position limits, exposure caps, and circuit breakers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from .config import RiskConfig
from .models import CopySignal, PortfolioSnapshot, Position

logger = logging.getLogger(__name__)


class RiskCheckResult:
    """Outcome of a risk check."""

    __slots__ = ("allowed", "reason", "adjusted_size")

    def __init__(
        self,
        allowed: bool,
        reason: str = "",
        adjusted_size: Optional[float] = None,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.adjusted_size = adjusted_size

    def __repr__(self) -> str:
        return f"RiskCheckResult(allowed={self.allowed}, reason={self.reason!r})"


class RiskManager:
    """Evaluates copy signals against risk limits before execution.

    Tracks portfolio state and enforces:
    - Per-position size limits
    - Total portfolio exposure cap
    - Max open positions
    - Price bounds (min/max)
    - Daily loss limit
    - Consecutive loss circuit breaker
    """

    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._positions: dict[str, Position] = {}
        self._daily_pnl: float = 0.0
        self._daily_reset_date: datetime = datetime.now(timezone.utc)
        self._consecutive_losses: int = 0
        self._paused: bool = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def resume(self) -> None:
        """Manually resume trading after a circuit breaker pause."""
        self._paused = False
        self._consecutive_losses = 0
        logger.info("Risk manager resumed")

    def check(self, signal: CopySignal) -> RiskCheckResult:
        """Evaluate a copy signal against all risk rules.

        Returns a RiskCheckResult indicating whether the trade is allowed,
        optionally with an adjusted size.
        """
        self._maybe_reset_daily()

        # Circuit breaker
        if self._paused:
            return RiskCheckResult(False, "Trading paused — circuit breaker active")

        # Daily loss limit
        if self._daily_pnl <= -self._config.daily_loss_limit_usdc:
            self._paused = True
            return RiskCheckResult(False, "Daily loss limit reached")

        # Price bounds
        if signal.target_price > self._config.max_price:
            return RiskCheckResult(False, f"Price {signal.target_price:.4f} exceeds max {self._config.max_price}")
        if signal.target_price < self._config.min_price:
            return RiskCheckResult(False, f"Price {signal.target_price:.4f} below min {self._config.min_price}")

        # Max open positions
        if len(self._positions) >= self._config.max_open_positions:
            if signal.source_trade.asset_id not in self._positions:
                return RiskCheckResult(False, f"Max open positions ({self._config.max_open_positions}) reached")

        # Total portfolio exposure
        total_exposure = sum(p.notional for p in self._positions.values())
        trade_notional = signal.target_size * signal.target_price
        if total_exposure + trade_notional > self._config.max_portfolio_exposure_usdc:
            available = max(0, self._config.max_portfolio_exposure_usdc - total_exposure)
            if available < signal.target_price:
                return RiskCheckResult(False, "Portfolio exposure limit reached")
            adjusted = available / signal.target_price
            return RiskCheckResult(True, "Size reduced to fit exposure limit", adjusted_size=adjusted)

        # Per-position size limit
        existing = self._positions.get(signal.source_trade.asset_id)
        current_notional = existing.notional if existing else 0
        if current_notional + trade_notional > self._config.max_position_size_usdc:
            available = max(0, self._config.max_position_size_usdc - current_notional)
            if available < signal.target_price:
                return RiskCheckResult(False, "Position size limit reached for this market")
            adjusted = available / signal.target_price
            return RiskCheckResult(True, "Size reduced to fit position limit", adjusted_size=adjusted)

        return RiskCheckResult(True, "All risk checks passed")

    def record_fill(self, asset_id: str, side: str, size: float, price: float, market_id: str = "") -> None:
        """Update internal position tracking after a fill."""
        pos = self._positions.get(asset_id)
        if side == "BUY":
            if pos:
                total_size = pos.size + size
                pos.avg_price = (pos.avg_price * pos.size + price * size) / total_size if total_size else price
                pos.size = total_size
            else:
                from .models import Position, TradeSide

                self._positions[asset_id] = Position(
                    market_id=market_id,
                    asset_id=asset_id,
                    side=TradeSide.BUY,
                    size=size,
                    avg_price=price,
                    current_price=price,
                )
        elif side == "SELL" and pos:
            pnl = (price - pos.avg_price) * min(size, pos.size)
            self._daily_pnl += pnl
            pos.size -= size
            if pos.size <= 0.001:
                del self._positions[asset_id]

            if pnl < 0:
                self._consecutive_losses += 1
                if self._consecutive_losses >= self._config.max_consecutive_losses:
                    self._paused = True
                    logger.warning("Circuit breaker triggered: %d consecutive losses", self._consecutive_losses)
            else:
                self._consecutive_losses = 0

    def get_snapshot(self) -> PortfolioSnapshot:
        """Build a current portfolio snapshot."""
        total_exposure = sum(p.notional for p in self._positions.values())
        unrealised = sum(p.unrealized_pnl for p in self._positions.values())
        return PortfolioSnapshot(
            total_value_usdc=total_exposure,
            open_positions=len(self._positions),
            total_exposure_usdc=total_exposure,
            daily_pnl_usdc=self._daily_pnl,
            unrealized_pnl_usdc=unrealised,
            consecutive_losses=self._consecutive_losses,
        )

    def _maybe_reset_daily(self) -> None:
        """Reset daily PnL counter at the start of each new day."""
        now = datetime.now(timezone.utc)
        if now.date() != self._daily_reset_date.date():
            self._daily_pnl = 0.0
            self._daily_reset_date = now
            if self._paused:
                logger.info("New day — resetting circuit breaker")
                self._paused = False
                self._consecutive_losses = 0
