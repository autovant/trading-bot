"""
WebSocket manager with connection registry, per-topic subscriptions, and NATS bridge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

VALID_TOPICS: Set[str] = {"positions", "fills", "alarms", "agents", "market"}

NATS_TOPIC_MAP: Dict[str, str] = {
    "trading.positions": "positions",
    "trading.executions": "fills",
    "risk.alarms": "alarms",
    "agent.status": "agents",
    "market.data": "market",
}

HEARTBEAT_INTERVAL = 15  # seconds
STALE_TIMEOUT = 30  # seconds


class _Connection:
    """Internal representation of a single WebSocket connection."""

    __slots__ = ("ws", "id", "topics", "last_pong", "_disconnecting")

    def __init__(self, ws: WebSocket, conn_id: str) -> None:
        self.ws = ws
        self.id = conn_id
        self.topics: Set[str] = set()
        self.last_pong: float = time.monotonic()
        self._disconnecting: bool = False


class WebSocketManager:
    """WebSocket manager with connection registry, per-topic subscriptions, and NATS bridge."""

    def __init__(self) -> None:
        self._connections: Dict[str, _Connection] = {}
        self._lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._nats_subscriptions: list = []

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a WebSocket and register it. Returns the connection id."""
        await websocket.accept()
        conn_id = uuid.uuid4().hex
        conn = _Connection(websocket, conn_id)
        async with self._lock:
            self._connections[conn_id] = conn
        logger.info("WS connected: %s (total=%d)", conn_id, len(self._connections))
        await self._send_json(websocket, {"type": "connected", "id": conn_id})
        return conn_id

    async def disconnect(self, conn_id: str) -> None:
        """Remove a connection from the registry."""
        async with self._lock:
            conn = self._connections.pop(conn_id, None)
        if conn:
            logger.info("WS disconnected: %s (total=%d)", conn_id, len(self._connections))
            try:
                if conn.ws.client_state == WebSocketState.CONNECTED:
                    await conn.ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    async def subscribe(self, conn_id: str, topics: list[str]) -> list[str]:
        """Subscribe a connection to the given topics. Returns the list of accepted topics."""
        valid = [t for t in topics if t in VALID_TOPICS]
        async with self._lock:
            conn = self._connections.get(conn_id)
            if conn:
                conn.topics.update(valid)
        return valid

    async def unsubscribe(self, conn_id: str, topics: list[str]) -> list[str]:
        """Unsubscribe a connection from the given topics."""
        valid = [t for t in topics if t in VALID_TOPICS]
        async with self._lock:
            conn = self._connections.get(conn_id)
            if conn:
                conn.topics.difference_update(valid)
        return valid

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, topic: str, data: Any) -> None:
        """Send *data* to every connection subscribed to *topic*."""
        message = json.dumps({"topic": topic, "data": data})
        async with self._lock:
            targets = [
                c for c in self._connections.values() if topic in c.topics
            ]
        for conn in targets:
            await self._send_text(conn, message)

    async def broadcast_all(self, data: Any) -> None:
        """Send a system message to **all** connected clients."""
        message = json.dumps({"topic": "system", "data": data})
        async with self._lock:
            targets = list(self._connections.values())
        for conn in targets:
            await self._send_text(conn, message)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def start_heartbeat(self) -> None:
        """Start the background heartbeat / stale-connection reaper."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("WS heartbeat task started")

    async def stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            logger.info("WS heartbeat task stopped")

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                now = time.monotonic()
                async with self._lock:
                    snapshot = list(self._connections.items())

                stale_ids: list[str] = []
                for conn_id, conn in snapshot:
                    if now - conn.last_pong > STALE_TIMEOUT:
                        stale_ids.append(conn_id)
                        continue
                    try:
                        await conn.ws.send_json({"type": "ping", "ts": time.time()})
                    except Exception:
                        stale_ids.append(conn_id)

                for conn_id in stale_ids:
                    logger.warning("Reaping stale WS connection: %s", conn_id)
                    await self.disconnect(conn_id)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # NATS bridge
    # ------------------------------------------------------------------

    async def start_nats_bridge(self, messaging_client: Any) -> None:
        """Subscribe to NATS subjects and forward messages to WS clients."""
        for nats_subject, ws_topic in NATS_TOPIC_MAP.items():
            try:
                sub = await messaging_client.subscribe(
                    nats_subject,
                    self._make_nats_handler(ws_topic),
                )
                self._nats_subscriptions.append(sub)
                logger.info("NATS→WS bridge: %s → %s", nats_subject, ws_topic)
            except Exception as exc:
                logger.error("Failed to bridge %s: %s", nats_subject, exc)

    async def stop_nats_bridge(self) -> None:
        for sub in self._nats_subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._nats_subscriptions.clear()

    def _make_nats_handler(self, ws_topic: str):
        async def _handler(msg: Any) -> None:
            try:
                payload = json.loads(msg.data.decode() if isinstance(msg.data, bytes) else msg.data)
            except (json.JSONDecodeError, AttributeError):
                payload = str(msg.data)
            await self.broadcast(ws_topic, payload)
        return _handler

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_json(ws: WebSocket, data: Any) -> None:
        try:
            await ws.send_json(data)
        except Exception:
            pass

    async def _send_text(self, conn: _Connection, text: str) -> None:
        try:
            await conn.ws.send_text(text)
        except Exception:
            # Connection likely dead – schedule removal (guard against double-disconnect)
            if not conn._disconnecting:
                conn._disconnecting = True
                asyncio.create_task(self.disconnect(conn.id))


# ------------------------------------------------------------------
# WebSocket endpoint handler
# ------------------------------------------------------------------

async def websocket_handler(websocket: WebSocket, manager: WebSocketManager) -> None:
    """Full WS lifecycle: accept, process messages, clean up."""
    conn_id = await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await WebSocketManager._send_json(websocket, {
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue

            action = msg.get("action")

            if action == "subscribe":
                topics = msg.get("topics", [])
                accepted = await manager.subscribe(conn_id, topics)
                await WebSocketManager._send_json(websocket, {
                    "type": "subscribed",
                    "topics": accepted,
                })

            elif action == "unsubscribe":
                topics = msg.get("topics", [])
                removed = await manager.unsubscribe(conn_id, topics)
                await WebSocketManager._send_json(websocket, {
                    "type": "unsubscribed",
                    "topics": removed,
                })

            elif action == "pong":
                # Client responding to our ping
                async with manager._lock:
                    conn = manager._connections.get(conn_id)
                    if conn:
                        conn.last_pong = time.monotonic()

            else:
                await WebSocketManager._send_json(websocket, {
                    "type": "error",
                    "message": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        await manager.disconnect(conn_id)
    except Exception as exc:
        logger.error("WS error for %s: %s", conn_id, exc)
        await manager.disconnect(conn_id)


# Singleton instance
ws_manager = WebSocketManager()
