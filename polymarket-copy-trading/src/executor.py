"""Order executor — places orders on Polymarket and tracks results."""

from __future__ import annotations

import logging
from typing import Optional

from .client import PolymarketClient
from .models import CopiedTrade, CopySignal, TradeStatus

logger = logging.getLogger(__name__)


class Executor:
    """Executes copy signals as orders on Polymarket.

    Supports dry-run mode where trades are logged but not submitted.
    """

    def __init__(
        self,
        client: PolymarketClient,
        dry_run: bool = True,
    ) -> None:
        self._client = client
        self._dry_run = dry_run

    async def execute(self, signal: CopySignal, adjusted_size: Optional[float] = None) -> CopiedTrade:
        """Execute a copy signal.

        Args:
            signal: The copy signal to execute.
            adjusted_size: Optional risk-adjusted size override.

        Returns:
            A CopiedTrade record with the execution result.
        """
        size = adjusted_size if adjusted_size is not None else signal.target_size
        trade = CopiedTrade(
            source_trade_id=signal.source_trade.trade_id,
            source_wallet=signal.source_trade.wallet,
            market_id=signal.source_trade.market_id,
            asset_id=signal.source_trade.asset_id,
            side=signal.target_side,
            price=signal.target_price,
            size=size,
        )

        if self._dry_run:
            trade.status = TradeStatus.FILLED
            trade.fill_price = signal.target_price
            trade.fill_size = size
            logger.info(
                "[DRY RUN] %s %.4f × %.2f on %s (source: %s)",
                signal.target_side.value,
                signal.target_price,
                size,
                signal.source_trade.asset_id[:12],
                signal.source_trade.wallet[:10],
            )
            return trade

        try:
            resp = await self._client.create_order(
                token_id=signal.source_trade.asset_id,
                side=signal.target_side.value,
                price=signal.target_price,
                size=size,
            )
            trade.order_id = str(resp.get("order_id", resp.get("orderID", "")))
            trade.status = TradeStatus.FILLED
            trade.fill_price = signal.target_price
            trade.fill_size = size
            logger.info(
                "Order placed: %s %.4f × %.2f on %s → %s",
                signal.target_side.value,
                signal.target_price,
                size,
                signal.source_trade.asset_id[:12],
                trade.order_id,
            )
        except Exception as exc:
            trade.status = TradeStatus.FAILED
            trade.error = str(exc)
            logger.error("Order execution failed: %s", exc)

        return trade
