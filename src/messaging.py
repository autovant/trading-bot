"""
NATS messaging system for inter-service communication.
"""

import json
import logging
from typing import Dict, Any, Optional, Callable

try:
    from nats.js import JetStreamContext
    from nats.aio.client import Client as NATS
    from nats.aio.msg import Msg
    from nats.aio.subscription import Subscription

    NATS_AVAILABLE = True
except ImportError:
    NATS_AVAILABLE = False
    logging.warning("NATS client not available. Messaging will be disabled.")

logger = logging.getLogger(__name__)


class MessagingClient:
    """NATS messaging client for pub/sub communication."""

    def __init__(self, config: Dict[str, Any]):
        if not NATS_AVAILABLE:
            logger.warning("NATS client not available. Messaging will be disabled.")
            self.config = config
            self.connected = False
            return

        self.config = config
        self.nc: Optional[NATS] = NATS()
        self.js: Optional[JetStreamContext] = None
        self.connected = False
        self.subscribers: Dict[str, Subscription] = {}

    async def connect(self):
        """Connect to NATS server."""
        try:
            servers = self.config.get("servers", ["nats://localhost:4222"])
            if self.nc:
                await self.nc.connect(servers=servers)
                self.connected = True
                logger.info(f"Connected to NATS servers: {servers}")
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise

    async def close(self):
        """Close NATS connection."""
        try:
            # Unsubscribe all subscribers
            for sub in self.subscribers.values():
                await sub.unsubscribe()

            # Close connection
            if self.nc:
                await self.nc.drain()
                await self.nc.close()
                self.connected = False
                logger.info("NATS connection closed")
        except Exception as e:
            logger.error(f"Error closing NATS connection: {e}")
            raise

    async def publish(self, subject: str, message: Dict[str, Any]):
        """Publish a message to a subject."""
        if not self.connected or not self.nc:
            logger.warning("Not connected to NATS, cannot publish message.")
            return
        try:
            await self.nc.publish(subject, json.dumps(message).encode())
        except Exception as e:
            logger.error(f"Failed to publish message to {subject}: {e}")

    async def subscribe(
        self, subject: str, callback: Callable
    ) -> Optional[Subscription]:
        """Subscribe to a subject."""
        if not self.connected or not self.nc:
            logger.warning("Not connected to NATS, cannot subscribe.")
            return None

        async def message_handler(msg: Msg):
            await callback(msg)

        try:
            sub = await self.nc.subscribe(subject, cb=message_handler)
            self.subscribers[subject] = sub
            return sub
        except Exception as e:
            logger.error(f"Failed to subscribe to {subject}: {e}")
            return None

    async def request(
        self, subject: str, message: Dict[str, Any], timeout: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """Send a request and wait for a response."""
        if not self.connected or not self.nc:
            logger.warning("Not connected to NATS, cannot send request.")
            return None
        try:
            response = await self.nc.request(
                subject, json.dumps(message).encode(), timeout=timeout
            )
            return json.loads(response.data)
        except Exception as e:
            logger.error(f"Request to {subject} failed: {e}")
            return None
