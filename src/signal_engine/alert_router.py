"""
Alert Router for the Confluence Signal Engine.

Multi-destination alert delivery:
- WebSocket stream
- Webhook notifier with HMAC signing
- Redis Pub/Sub (optional stub)
- Idempotent delivery
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

import aiohttp

from src.signal_engine.schemas import AlertPayload, SignalOutput, WebhookDestination

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections for real-time signal streaming.
    """
    
    def __init__(self):
        # Connections per subscription key: (exchange, symbol, tf) -> set of websockets
        self._connections: Dict[tuple, Set] = {}
        self._all_connections: Set = set()
    
    def add_connection(
        self,
        websocket,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        """
        Add a WebSocket connection.
        
        If exchange/symbol/timeframe are provided, subscribe to that specific feed.
        Otherwise, subscribe to all signals.
        """
        if exchange and symbol and timeframe:
            key = (exchange, symbol, timeframe)
            if key not in self._connections:
                self._connections[key] = set()
            self._connections[key].add(websocket)
        
        self._all_connections.add(websocket)
    
    def remove_connection(self, websocket) -> None:
        """Remove a WebSocket connection."""
        self._all_connections.discard(websocket)
        
        for key in list(self._connections.keys()):
            self._connections[key].discard(websocket)
            if not self._connections[key]:
                del self._connections[key]
    
    async def broadcast(self, signal: SignalOutput) -> int:
        """
        Broadcast signal to relevant WebSocket connections.
        
        Returns number of clients notified.
        """
        key = (signal.exchange, signal.symbol, signal.timeframe)
        payload = AlertPayload.from_signal(signal).model_dump_json()
        
        # Get connections subscribed to this specific feed
        specific_connections = self._connections.get(key, set())
        
        # Combine with all-feed subscribers
        # (In production, you'd want to differentiate these more carefully)
        all_to_notify = specific_connections | self._all_connections
        
        notified = 0
        for ws in list(all_to_notify):
            try:
                await ws.send_text(payload)
                notified += 1
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                self.remove_connection(ws)
        
        return notified
    
    @property
    def connection_count(self) -> int:
        return len(self._all_connections)


class WebhookNotifier:
    """
    Sends alerts to configured webhook endpoints with retry and HMAC signing.
    """
    
    def __init__(
        self,
        destinations: List[WebhookDestination],
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.destinations = destinations
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _sign_payload(self, payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for payload."""
        return hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
    
    async def send(self, signal: SignalOutput) -> Dict[str, bool]:
        """
        Send signal to all configured webhook destinations.
        
        Returns dict of URL -> success status.
        """
        payload = AlertPayload.from_signal(signal)
        payload_json = payload.model_dump_json()
        
        results = {}
        
        for dest in self.destinations:
            if not dest.enabled:
                continue
            
            success = await self._send_to_destination(dest, payload_json)
            results[dest.url] = success
        
        return results
    
    async def _send_to_destination(
        self,
        dest: WebhookDestination,
        payload_json: str,
    ) -> bool:
        """Send to a single destination with retry."""
        session = await self._get_session()
        
        headers = {
            "Content-Type": "application/json",
            "X-Timestamp": str(int(time.time())),
        }
        
        # Add HMAC signature if secret is configured
        if dest.secret:
            signature = self._sign_payload(payload_json, dest.secret)
            headers["X-Signature"] = signature
        
        for attempt in range(dest.retry_count or self.max_retries):
            try:
                async with session.post(
                    dest.url,
                    data=payload_json,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=dest.timeout_seconds),
                ) as response:
                    if response.status < 300:
                        logger.info(f"Webhook delivered to {dest.url}")
                        return True
                    else:
                        logger.warning(
                            f"Webhook to {dest.url} returned {response.status}"
                        )
            except asyncio.TimeoutError:
                logger.warning(f"Webhook to {dest.url} timed out")
            except Exception as e:
                logger.warning(f"Webhook to {dest.url} failed: {e}")
            
            if attempt < (dest.retry_count or self.max_retries) - 1:
                delay = self.retry_delay * (2 ** attempt)
                await asyncio.sleep(delay)
        
        logger.error(f"Webhook to {dest.url} failed after all retries")
        return False


class RedisPubSubInterface:
    """
    Interface for Redis Pub/Sub (stub implementation).
    
    Can be replaced with actual Redis implementation when needed.
    """
    
    def __init__(self, url: Optional[str] = None, channel: str = "signals"):
        self.url = url
        self.channel = channel
        self._enabled = bool(url)
        self._client = None
    
    async def connect(self) -> bool:
        """Connect to Redis (stub)."""
        if not self._enabled:
            return False
        
        # Stub: In production, use aioredis or similar
        logger.info(f"Redis Pub/Sub stub: would connect to {self.url}")
        return True
    
    async def publish(self, signal: SignalOutput) -> bool:
        """Publish signal to Redis channel (stub)."""
        if not self._enabled:
            return False
        
        payload = AlertPayload.from_signal(signal)
        logger.info(
            f"Redis Pub/Sub stub: would publish to {self.channel}: "
            f"{signal.side.value} {signal.symbol}"
        )
        return True
    
    async def close(self) -> None:
        """Close Redis connection (stub)."""
        pass


class AlertRouter:
    """
    Routes alerts to multiple destinations.
    
    Supports:
    - WebSocket streaming
    - Webhook notifications
    - Redis Pub/Sub (optional)
    
    Tracks delivered signals for idempotency.
    """
    
    def __init__(
        self,
        websocket_enabled: bool = True,
        webhooks: Optional[List[WebhookDestination]] = None,
        redis_url: Optional[str] = None,
        redis_channel: str = "signals",
    ):
        self.websocket_enabled = websocket_enabled
        
        self.ws_manager = WebSocketManager() if websocket_enabled else None
        self.webhook_notifier = WebhookNotifier(webhooks or [])
        self.redis = RedisPubSubInterface(redis_url, redis_channel)
        
        # Track delivered signals for idempotency
        self._delivered: Set[str] = set()
        self._max_delivered = 10000
    
    async def route(self, signal: SignalOutput) -> Dict[str, Any]:
        """
        Route signal to all configured destinations.
        
        Returns dict with delivery status per destination type.
        """
        # Check idempotency
        if signal.idempotency_key in self._delivered:
            logger.debug(f"Duplicate alert blocked: {signal.idempotency_key}")
            return {"status": "duplicate", "delivered": False}
        
        results = {
            "idempotency_key": signal.idempotency_key,
            "delivered": True,
            "destinations": {},
        }
        
        # WebSocket broadcast
        if self.ws_manager:
            try:
                ws_count = await self.ws_manager.broadcast(signal)
                results["destinations"]["websocket"] = {
                    "success": True,
                    "clients": ws_count,
                }
            except Exception as e:
                logger.error(f"WebSocket broadcast failed: {e}")
                results["destinations"]["websocket"] = {
                    "success": False,
                    "error": str(e),
                }
        
        # Webhook notifications
        if self.webhook_notifier.destinations:
            try:
                webhook_results = await self.webhook_notifier.send(signal)
                results["destinations"]["webhooks"] = webhook_results
            except Exception as e:
                logger.error(f"Webhook notifications failed: {e}")
                results["destinations"]["webhooks"] = {"error": str(e)}
        
        # Redis Pub/Sub
        if self.redis._enabled:
            try:
                redis_success = await self.redis.publish(signal)
                results["destinations"]["redis"] = {"success": redis_success}
            except Exception as e:
                logger.error(f"Redis publish failed: {e}")
                results["destinations"]["redis"] = {"success": False, "error": str(e)}
        
        # Mark as delivered
        self._delivered.add(signal.idempotency_key)
        self._prune_delivered()
        
        return results
    
    def _prune_delivered(self) -> None:
        """Prune old delivered keys."""
        if len(self._delivered) > self._max_delivered:
            to_remove = len(self._delivered) - (self._max_delivered // 2)
            for _ in range(to_remove):
                if self._delivered:
                    self._delivered.pop()
    
    async def close(self) -> None:
        """Close all connections."""
        await self.webhook_notifier.close()
        await self.redis.close()
    
    def add_websocket(
        self,
        websocket,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        """Add a WebSocket connection."""
        if self.ws_manager:
            self.ws_manager.add_connection(websocket, exchange, symbol, timeframe)
    
    def remove_websocket(self, websocket) -> None:
        """Remove a WebSocket connection."""
        if self.ws_manager:
            self.ws_manager.remove_connection(websocket)
