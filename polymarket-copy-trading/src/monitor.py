"""Trade monitor — watches source wallets for new trades and emits SourceTrade events."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

from .client import PolymarketClient
from .config import AppConfig
from .models import SourceTrade, TradeSide

logger = logging.getLogger(__name__)

# Type alias for the callback invoked when a new trade is detected
TradeCallback = Callable[[SourceTrade], None]


class TradeMonitor:
    """Polls source wallets for new trades and notifies listeners.

    Maintains a set of already-seen trade IDs to avoid duplicate signals.
    """

    def __init__(
        self,
        config: AppConfig,
        client: PolymarketClient,
    ) -> None:
        self._config = config
        self._client = client
        self._seen_trade_ids: Set[str] = set()
        self._callbacks: List[TradeCallback] = []
        self._running = False

    def on_trade(self, callback: TradeCallback) -> None:
        """Register a callback to be invoked for each new source trade."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Begin polling source wallets."""
        self._running = True
        logger.info(
            "Trade monitor started — watching %d wallet(s), poll every %ds",
            len(self._config.source_wallets),
            self._config.poll_interval_seconds,
        )
        while self._running:
            try:
                await self._poll_all_wallets()
            except Exception:
                logger.exception("Error during wallet polling cycle")
            await asyncio.sleep(self._config.poll_interval_seconds)

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        logger.info("Trade monitor stopped")

    async def _poll_all_wallets(self) -> None:
        """Poll each source wallet for new trades."""
        for wallet in self._config.source_wallets:
            try:
                new_trades = await self._poll_wallet(wallet)
                for trade in new_trades:
                    self._emit(trade)
            except Exception:
                logger.exception("Failed to poll wallet %s", wallet)

    async def _poll_wallet(self, wallet: str) -> List[SourceTrade]:
        """Fetch recent trades for a wallet and return only unseen ones."""
        raw_trades = await self._client.get_wallet_trades(wallet)
        new_trades: List[SourceTrade] = []

        for raw in raw_trades:
            trade_id = self._extract_trade_id(raw)
            if trade_id in self._seen_trade_ids:
                continue

            trade = self._parse_trade(raw, wallet)
            if trade is None:
                continue

            # Skip trades older than the configured threshold
            age = (datetime.now(timezone.utc) - trade.timestamp).total_seconds()
            if age > self._config.copy.max_trade_age_seconds:
                self._seen_trade_ids.add(trade_id)
                continue

            self._seen_trade_ids.add(trade_id)
            new_trades.append(trade)

        if new_trades:
            logger.info("Wallet %s: %d new trade(s) detected", wallet[:10], len(new_trades))

        return new_trades

    def _emit(self, trade: SourceTrade) -> None:
        """Notify all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(trade)
            except Exception:
                logger.exception("Trade callback error")

    # ── Parsing helpers ───────────────────────────────────────────────

    @staticmethod
    def _extract_trade_id(raw: Dict) -> str:
        """Extract a unique trade identifier from raw API data."""
        return str(raw.get("id", raw.get("tradeId", raw.get("trade_id", id(raw)))))

    @staticmethod
    def _parse_trade(raw: Dict, wallet: str) -> Optional[SourceTrade]:
        """Convert a raw API trade dict into a SourceTrade model."""
        try:
            side_str = str(raw.get("side", raw.get("type", "BUY"))).upper()
            side = TradeSide.BUY if side_str == "BUY" else TradeSide.SELL

            price = float(raw.get("price", 0))
            size = float(raw.get("size", raw.get("amount", 0)))
            if price <= 0 or size <= 0:
                return None

            ts_raw = raw.get("timestamp", raw.get("created_at"))
            if isinstance(ts_raw, (int, float)):
                timestamp = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            elif isinstance(ts_raw, str):
                timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now(timezone.utc)

            return SourceTrade(
                trade_id=TradeMonitor._extract_trade_id(raw),
                wallet=wallet,
                market_id=str(raw.get("market", raw.get("market_id", raw.get("condition_id", "")))),
                asset_id=str(raw.get("asset_id", raw.get("token_id", ""))),
                side=side,
                price=price,
                size=size,
                timestamp=timestamp,
                market_question=str(raw.get("question", raw.get("market_question", ""))),
                outcome=str(raw.get("outcome", "")),
            )
        except Exception:
            logger.warning("Failed to parse trade: %s", raw)
            return None
