"""
NATS messaging system for inter-service communication.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing aides
    from nats.aio.msg import Msg as MsgT
    from nats.aio.subscription import Subscription as SubscriptionT
    from nats.js import JetStreamContext as JetStreamContextT
else:
    MsgT = Any
    SubscriptionT = Any
    JetStreamContextT = Any

try:
    _nats_client_module = importlib.import_module("nats.aio.client")
    _nats_js_module = importlib.import_module("nats.js")
    _NATSClientFactory = getattr(_nats_client_module, "Client", None)
    _JetStreamContextFactory = getattr(_nats_js_module, "JetStreamContext", None)
    NATS_AVAILABLE = bool(_NATSClientFactory)
except ImportError:  # pragma: no cover - optional dependency
    _NATSClientFactory = None
    _JetStreamContextFactory = None
    NATS_AVAILABLE = False
    logging.warning("NATS client not available. Messaging will be disabled.")

logger = logging.getLogger(__name__)


class MessagingClient:
    """NATS messaging client with resilience and auto-reconnect support."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.nc: Optional[Any] = (
            _NATSClientFactory() if callable(_NATSClientFactory) else None
        )
        self.js: Optional[JetStreamContextT] = None
        self.connected = False

        self.subscribers: Dict[str, SubscriptionT] = {}
        self._callbacks: Dict[str, Callable[[MsgT], Awaitable[None]]] = {}
        self._connect_lock = asyncio.Lock()
        self._needs_restore = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        max_retries_cfg = config.get("max_retries")
        self._max_retries = int(max_retries_cfg) if max_retries_cfg is not None else 5
        self._publish_retries = int(config.get("publish_max_retries", 3))
        self._initial_backoff = float(config.get("initial_backoff", 0.5))
        self._max_backoff = float(config.get("max_backoff", 5.0))
        self._reconnect_time_wait = float(config.get("reconnect_time_wait", 1.0))
        self._connect_timeout = float(config.get("connect_timeout", 2.0))

    def _is_nc_connected(self) -> bool:
        return bool(
            self.nc
            and getattr(self.nc, "is_connected", False)
            and not getattr(self.nc, "is_closed", False)
        )

    def _set_disconnected(self) -> None:
        self.connected = False
        self._needs_restore = True

    def _compute_backoff(self, attempt: int) -> float:
        exponent = max(attempt, 0)
        delay = self._initial_backoff * (2**exponent)
        return min(delay, self._max_backoff)

    async def _restore_subscriptions(self) -> None:
        if not self._needs_restore or not self._callbacks:
            self._needs_restore = False
            return
        if not self.connected or not self.nc:
            return

        for subject, handler in self._callbacks.items():
            try:
                subscription = await self.nc.subscribe(subject, cb=handler)
                self.subscribers[subject] = subscription
            except Exception as exc:  # pragma: no cover - best effort logging
                logger.error("Failed to restore subscription for %s: %s", subject, exc)
        self._needs_restore = False

    async def _ensure_connection(self) -> bool:
        if not NATS_AVAILABLE:
            return False
        if self.connected and self._is_nc_connected():
            if self._needs_restore:
                await self._restore_subscriptions()
            return True

        try:
            await self.connect()
        except Exception:
            return False

        return self.connected and self._is_nc_connected()

    async def connect(self, timeout: Optional[float] = 10.0):
        """Connect to NATS server with retry/backoff logic."""

        async def _connect_inner() -> None:
            if not NATS_AVAILABLE:
                logger.warning("NATS client not available. Messaging will be disabled.")
                return

            if self.nc is None:
                if not callable(_NATSClientFactory):
                    logger.warning("NATS client factory unavailable; messaging disabled.")
                    return
                self.nc = _NATSClientFactory()

            if self.connected and self._is_nc_connected():
                return

            async with self._connect_lock:
                if self.connected and self._is_nc_connected():
                    return

                servers = self.config.get("servers", ["nats://localhost:4222"])
                attempts = 0
                max_attempts = self._max_retries if self._max_retries > 0 else None

                while max_attempts is None or attempts < max_attempts:
                    attempts += 1
                    try:
                        self._loop = asyncio.get_running_loop()
                    except RuntimeError:
                        self._loop = None

                    try:
                        await self.nc.connect(
                            servers=servers,
                            allow_reconnect=True,
                            max_reconnect_attempts=-1,
                            reconnect_time_wait=self._reconnect_time_wait,
                            connect_timeout=self._connect_timeout,
                            error_cb=self._on_error,
                            disconnected_cb=self._on_disconnected,
                            reconnected_cb=self._on_reconnected,
                            closed_cb=self._on_closed,
                        )
                        self.connected = True
                        self._needs_restore = True
                        await self._restore_subscriptions()
                        logger.info("Connected to NATS servers: %s", servers)
                        return
                    except Exception as exc:
                        self._set_disconnected()
                        if max_attempts is not None and attempts >= max_attempts:
                            logger.error(
                                "Failed to connect to NATS after %s attempts: %s",
                                attempts,
                                exc,
                            )
                            raise
                        delay = self._compute_backoff(attempts - 1)
                        logger.warning(
                            "NATS connection attempt %s failed: %s; retrying in %.2fs",
                            attempts,
                            exc,
                            delay,
                        )
                        await asyncio.sleep(delay)

        if timeout is None or timeout <= 0:
            await _connect_inner()
            return

        try:
            await asyncio.wait_for(_connect_inner(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._set_disconnected()
            raise TimeoutError(f"NATS connect timed out after {timeout}s") from exc

    async def _on_error(self, error: Exception) -> None:
        logger.error("NATS client error: %s", error)

    async def _on_disconnected(self) -> None:
        logger.warning("Disconnected from NATS.")
        self._set_disconnected()

    async def _on_reconnected(self) -> None:
        logger.info("Reconnected to NATS.")
        self.connected = True
        self._needs_restore = True
        await self._restore_subscriptions()

    async def _on_closed(self) -> None:
        logger.warning("NATS connection closed.")
        self._set_disconnected()

    async def close(self):
        """Close NATS connection."""
        if not NATS_AVAILABLE:
            self.connected = False
            self.subscribers.clear()
            self._callbacks.clear()
            self._needs_restore = True
            return

        try:
            for sub in list(self.subscribers.values()):
                try:
                    await sub.unsubscribe()
                except Exception as exc:
                    logger.debug("Failed to unsubscribe from %s: %s", sub.subject, exc)

            if self.nc:
                await self.nc.drain()
                await self.nc.close()
                self.connected = False
                logger.info("NATS connection closed")
        except Exception as exc:
            logger.error(f"Error closing NATS connection: {exc}")
            raise
        finally:
            self.subscribers.clear()
            self._callbacks.clear()
            self._needs_restore = True

    async def publish(self, subject: str, message: Dict[str, Any]):
        """Publish a message to a subject with retry/backoff."""
        if not NATS_AVAILABLE:
            logger.warning(
                "NATS client not available. Dropping message for subject %s.",
                subject,
            )
            return

        try:
            payload = json.dumps(message).encode()
        except (TypeError, ValueError) as exc:
            logger.error("Failed to serialise message for %s: %s", subject, exc)
            return

        attempts = 0
        total_attempts = max(self._publish_retries, 0) + 1

        while attempts < total_attempts:
            attempts += 1
            if not await self._ensure_connection():
                logger.warning("Unable to publish to %s; NATS unavailable.", subject)
                return
            if self.nc is None:
                logger.warning(
                    "Publishing aborted for %s; NATS client not initialised.", subject
                )
                return

            try:
                await self.nc.publish(subject, payload)
                return
            except Exception as exc:
                self._set_disconnected()
                if attempts >= total_attempts:
                    logger.error(
                        "Failed to publish message to %s after %s attempts: %s",
                        subject,
                        attempts,
                        exc,
                    )
                    return
                delay = self._compute_backoff(attempts - 1)
                logger.warning(
                    "Publish attempt %s to %s failed: %s; retrying in %.2fs",
                    attempts,
                    subject,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

    async def subscribe(
        self, subject: str, callback: Callable[[MsgT], Awaitable[None] | None]
    ) -> Optional[SubscriptionT]:
        """Subscribe to a subject."""
        if not NATS_AVAILABLE:
            logger.warning(
                "NATS client not available. Cannot subscribe to %s.", subject
            )
            return None

        if not await self._ensure_connection():
            logger.warning("Unable to subscribe to %s; NATS unavailable.", subject)
            return None
        if self.nc is None:
            logger.warning("Subscription aborted for %s; NATS client missing.", subject)
            return None

        async def message_handler(msg: MsgT):
            try:
                result = callback(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # pragma: no cover - callback side effects
                logger.exception(
                    "Subscription callback for %s raised an error: %s", subject, exc
                )

        try:
            existing = self.subscribers.get(subject)
            if existing:
                try:
                    await existing.unsubscribe()
                except Exception:
                    pass

            self._callbacks[subject] = message_handler
            sub = await self.nc.subscribe(subject, cb=message_handler)
            self.subscribers[subject] = sub
            return sub
        except Exception as exc:
            self._set_disconnected()
            logger.error(f"Failed to subscribe to {subject}: {exc}")
            return None

    async def request(
        self, subject: str, message: Dict[str, Any], timeout: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """Send a request and wait for a response with retry/backoff."""
        if not NATS_AVAILABLE:
            logger.warning("NATS client not available. Request to %s skipped.", subject)
            return None

        try:
            payload = json.dumps(message).encode()
        except (TypeError, ValueError) as exc:
            logger.error("Failed to serialise request payload for %s: %s", subject, exc)
            return None

        attempts = 0
        total_attempts = max(self._publish_retries, 0) + 1

        while attempts < total_attempts:
            attempts += 1
            if not await self._ensure_connection():
                logger.warning(
                    "Unable to submit request to %s; NATS unavailable.", subject
                )
                return None
            if self.nc is None:
                logger.warning(
                    "Request aborted for %s; NATS client not initialised.", subject
                )
                return None

            try:
                response = await self.nc.request(subject, payload, timeout=timeout)
                try:
                    return json.loads(response.data)
                except json.JSONDecodeError as exc:
                    logger.error("Failed to decode response from %s: %s", subject, exc)
                    return None
            except asyncio.TimeoutError:
                logger.warning("Request to %s timed out after %.2fs", subject, timeout)
                return None
            except Exception as exc:
                self._set_disconnected()
                if attempts >= total_attempts:
                    logger.error(
                        "Request to %s failed after %s attempts: %s",
                        subject,
                        attempts,
                        exc,
                    )
                    return None
                delay = self._compute_backoff(attempts - 1)
                logger.warning(
                    "Request attempt %s to %s failed: %s; retrying in %.2fs",
                    attempts,
                    subject,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        return None


class MockMessagingClient:
    """Mock messaging client for when NATS is unavailable."""
    
    async def connect(self, timeout: float = 1.0):
        logger.warning("Using MockMessagingClient (NATS unavailable)")

    async def close(self):
        pass

    async def publish(self, subject: str, message: Dict[str, Any]):
        logger.info(f"Mock publish to {subject}: {message}")

    async def subscribe(self, subject: str, callback: Any):
        logger.info(f"Mock subscribe to {subject}")
        return None

    async def request(self, subject: str, message: Dict[str, Any], timeout: float = 1.0):
        logger.info(f"Mock request to {subject}: {message}")
        return None
