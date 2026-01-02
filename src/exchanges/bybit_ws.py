import asyncio
import hmac
import hashlib
import json
import logging
import time
from typing import Dict, Any, Callable, Optional, List

import websockets
from websockets.client import Connect

from ..messaging import MessagingClient

logger = logging.getLogger(__name__)

class BybitWebsocketClient:
    """
    Bybit V5 Private Websocket Client for real-time order updates.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        messaging: MessagingClient,
        testnet: bool = True,
        ping_interval: int = 20,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.messaging = messaging
        self.testnet = testnet
        self.ping_interval = ping_interval
        
        self.url = (
            "wss://stream-testnet.bybit.com/v5/private"
            if testnet
            else "wss://stream.bybit.com/v5/private"
        )
        
        self.ws = None
        self.running = False
        self._tasks: List[asyncio.Task] = []

    def _generate_signature(self, expires: int) -> str:
        signature_payload = f"GET/realtime{expires}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            signature_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def connect(self):
        """Connect to the websocket."""
        logger.info(f"Connecting to Bybit WS: {self.url}")
        async with websockets.connect(self.url) as ws:
            self.ws = ws
            self.running = True
            
            # Authenticate
            await self._authenticate()
            
            # Subscribe
            await self._subscribe(["order"])

            # Start heartbeat
            heartbeat_task = asyncio.create_task(self._heartbeat())
            self._tasks.append(heartbeat_task)

            try:
                await self._listen()
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Bybit WS connection closed")
            except Exception as e:
                logger.error(f"Bybit WS error: {e}")
            finally:
                self.running = False
                heartbeat_task.cancel()

    async def _authenticate(self):
        expires = int((time.time() + 10) * 1000)
        signature = self._generate_signature(expires)
        
        auth_msg = {
            "op": "auth",
            "args": [self.api_key, expires, signature]
        }
        await self.ws.send(json.dumps(auth_msg))
        logger.info("Sent authentication request")

    async def _subscribe(self, topics: List[str]):
        msg = {
            "op": "subscribe",
            "args": topics
        }
        await self.ws.send(json.dumps(msg))
        logger.info(f"Subscribed to topics: {topics}")

    async def _heartbeat(self):
        while self.running:
            await asyncio.sleep(self.ping_interval)
            if self.ws and self.ws.open:
                try:
                    await self.ws.send(json.dumps({"op": "ping"}))
                    logger.debug("Sent ping")
                except Exception as e:
                    logger.error(f"Failed to send ping: {e}")
                    break

    async def _listen(self):
        async for message in self.ws:
            try:
                data = json.loads(message)
                await self._handle_message(data)
            except Exception as e:
                logger.error(f"Error handling message: {e}")

    async def _handle_message(self, data: Dict[str, Any]):
        op = data.get("op")
        if op == "pong":
            logger.debug("Received pong")
            return
        
        if op == "auth":
            if data.get("success"):
                logger.info("Bybit WS Authenticated successfully")
            else:
                logger.error(f"Authentication failed: {data}")
            return

        topic = data.get("topic")
        if topic == "order":
            await self._process_order_update(data)

    async def _process_order_update(self, data: Dict[str, Any]):
        # data['data'] is a list of order updates
        updates = data.get("data", [])
        for update in updates:
            logger.info(f"Received order update: {update.get('orderId')} status={update.get('orderStatus')}")
            # Publish to NATS
            # Subject: trading.orders.update (appending .update to base subject inferred)
            # Or use the configured subject. configuring/strategy.yaml has trading.orders
            await self.messaging.publish("trading.orders.update", update)

    async def start(self):
        while True:
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"Connection loop error: {e}")
            
            logger.info("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
