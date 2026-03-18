"""Copy engine — processes source trades into sized copy signals and orchestrates execution."""

from __future__ import annotations

import logging
from typing import Optional

from .config import AppConfig
from .models import CopySignal, SourceTrade, TradeSide

logger = logging.getLogger(__name__)


class CopyEngine:
    """Converts detected source trades into actionable copy signals.

    Responsibilities:
    - Decide whether to copy a trade (filter logic)
    - Calculate target position size based on sizing mode
    - Apply minimum trade size filters
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def process(self, trade: SourceTrade) -> Optional[CopySignal]:
        """Evaluate a source trade and optionally produce a CopySignal.

        Returns None if the trade should be skipped.
        """
        # Skip sells if configured
        if trade.side == TradeSide.SELL and not self._config.copy.copy_sells:
            logger.debug("Skipping SELL trade (copy_sells disabled): %s", trade.trade_id)
            return None

        # Calculate target size
        target_size = self._calculate_size(trade)
        if target_size is None:
            return None

        # Use the source price as the target price
        target_price = trade.price

        return CopySignal(
            source_trade=trade,
            target_side=trade.side,
            target_price=target_price,
            target_size=target_size,
            reason=f"Copy {trade.side.value} from {trade.wallet[:10]}…",
        )

    def _calculate_size(self, trade: SourceTrade) -> Optional[float]:
        """Calculate the target trade size based on the configured sizing mode."""
        cfg = self._config.copy

        if cfg.sizing_mode == "fixed":
            size_usdc = cfg.fixed_size_usdc
            target_size = size_usdc / trade.price if trade.price > 0 else 0
        else:
            # Proportional: mirror source size scaled by multiplier
            target_size = trade.size * cfg.size_multiplier

        # Apply minimum trade size filter
        notional = target_size * trade.price
        if notional < cfg.min_trade_size_usdc:
            logger.debug(
                "Trade too small (%.2f USDC < %.2f min): %s",
                notional,
                cfg.min_trade_size_usdc,
                trade.trade_id,
            )
            return None

        return round(target_size, 6)
