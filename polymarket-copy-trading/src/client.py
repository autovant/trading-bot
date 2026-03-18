"""Polymarket API client wrapper for market data, wallet monitoring, and order execution."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

import aiohttp

from .config import PolymarketConfig

logger = logging.getLogger(__name__)


class OrderClient(Protocol):
    """Protocol for placing orders (allows mocking for dry-run)."""

    async def create_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> Dict[str, Any]: ...

    async def cancel_order(self, order_id: str) -> bool: ...


class PolymarketClient:
    """Async wrapper around Polymarket's CLOB and Gamma APIs.

    Handles:
    - Market data retrieval (questions, prices, order books)
    - Wallet trade history monitoring
    - Order placement and cancellation
    """

    def __init__(self, config: PolymarketConfig) -> None:
        self._config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._clob_client: Any = None

    async def start(self) -> None:
        """Initialize HTTP session and CLOB client."""
        self._session = aiohttp.ClientSession()
        if self._config.private_key:
            try:
                from py_clob_client.client import ClobClient

                self._clob_client = ClobClient(
                    self._config.clob_url,
                    key=self._config.private_key,
                    chain_id=self._config.chain_id,
                )
                creds = self._clob_client.create_or_derive_api_creds()
                self._clob_client.set_api_creds(creds)
                logger.info("CLOB client authenticated successfully")
            except Exception:
                logger.warning("Failed to initialize CLOB client — running in read-only mode")
                self._clob_client = None
        else:
            logger.info("No private key configured — running in read-only mode")

    async def stop(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Market Data ───────────────────────────────────────────────────

    async def get_markets(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Fetch active markets from the Gamma API."""
        url = f"{self._config.gamma_url}/markets"
        params = {"limit": limit, "offset": offset, "active": "true"}
        return await self._get_json(url, params=params) or []

    async def get_market(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single market by its condition ID."""
        url = f"{self._config.gamma_url}/markets/{condition_id}"
        return await self._get_json(url)

    async def get_orderbook(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the order book for a specific token."""
        if self._clob_client:
            try:
                return self._clob_client.get_order_book(token_id)
            except Exception as exc:
                logger.warning("CLOB orderbook fetch failed: %s", exc)
        return None

    async def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get the midpoint price for a token."""
        if self._clob_client:
            try:
                mid = self._clob_client.get_midpoint(token_id)
                return float(mid) if mid else None
            except Exception as exc:
                logger.warning("Midpoint fetch failed: %s", exc)
        return None

    # ── Wallet Monitoring ─────────────────────────────────────────────

    async def get_wallet_trades(
        self,
        wallet: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch recent trades for a given wallet address.

        Uses the CLOB API's /trades endpoint filtered by maker address.
        """
        url = f"{self._config.clob_url}/trades"
        params = {"maker_address": wallet, "limit": limit}
        data = await self._get_json(url, params=params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data", data.get("trades", []))
        return []

    async def get_wallet_positions(self, wallet: str) -> List[Dict[str, Any]]:
        """Fetch open positions for a wallet (via Gamma API)."""
        url = f"{self._config.gamma_url}/positions"
        params = {"user": wallet}
        data = await self._get_json(url, params=params)
        return data if isinstance(data, list) else []

    # ── Order Execution ───────────────────────────────────────────────

    async def create_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> Dict[str, Any]:
        """Place an order on the CLOB.

        Args:
            token_id: The token (outcome) to trade.
            side: "BUY" or "SELL".
            price: Limit price per share (0-1 range for binary markets).
            size: Number of shares.

        Returns:
            Order response dict with at least ``order_id``.
        """
        if not self._clob_client:
            raise RuntimeError("CLOB client not initialised — cannot place orders")

        from py_clob_client.order_builder.constants import BUY, SELL

        clob_side = BUY if side.upper() == "BUY" else SELL
        order_args = {
            "token_id": token_id,
            "price": price,
            "size": size,
            "side": clob_side,
        }
        signed = self._clob_client.create_order(order_args)
        resp = self._clob_client.post_order(signed)
        logger.info("Order placed: token=%s side=%s price=%.4f size=%.2f", token_id, side, price, size)
        return resp if isinstance(resp, dict) else {"order_id": str(resp), "status": "PLACED"}

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if not self._clob_client:
            return False
        try:
            self._clob_client.cancel(order_id)
            logger.info("Order cancelled: %s", order_id)
            return True
        except Exception as exc:
            logger.warning("Cancel failed for %s: %s", order_id, exc)
            return False

    # ── Helpers ────────────────────────────────────────────────────────

    async def _get_json(
        self, url: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Perform a GET request and return parsed JSON."""
        if not self._session or self._session.closed:
            raise RuntimeError("HTTP session not started — call start() first")
        try:
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                return await resp.json()
        except Exception as exc:
            logger.warning("HTTP GET %s failed: %s", url, exc)
            return None


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)
