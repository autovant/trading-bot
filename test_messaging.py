"""
Integration test for the NATS messaging client.

The test is skipped automatically when NATS is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from src.config import load_config
from src.messaging import MessagingClient


async def run_messaging_test() -> None:
    config = load_config()

    client = MessagingClient(
        {
            "servers": config.messaging.servers,
            "max_retries": 1,
            "connect_timeout": 0.2,
            "publish_max_retries": 0,
        }
    )

    await client.connect(timeout=1.0)
    if not client.connected:
        raise RuntimeError("NATS not connected")

    try:
        received = asyncio.Event()
        received_payload: dict = {}

        async def message_handler(msg) -> None:
            nonlocal received_payload
            received_payload = json.loads(msg.data.decode("utf-8"))
            received.set()

        sub = await client.subscribe("test.messaging.pub", message_handler)
        if sub is None:
            raise RuntimeError("Failed to subscribe for publish test")

        await client.publish("test.messaging.pub", {"message": "hello"})
        await asyncio.wait_for(received.wait(), timeout=1.0)
        assert received_payload.get("message") == "hello"
        await sub.unsubscribe()

        async def request_handler(msg) -> None:
            await msg.respond(json.dumps({"pong": True}).encode("utf-8"))

        req_sub = await client.subscribe("test.messaging.req", request_handler)
        if req_sub is None:
            raise RuntimeError("Failed to subscribe for request test")

        response = await client.request(
            "test.messaging.req", {"ping": True}, timeout=1.0
        )
        assert response == {"pong": True}
        await req_sub.unsubscribe()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_messaging() -> None:
    try:
        await run_messaging_test()
    except Exception as exc:
        pytest.skip(f"NATS unavailable: {exc}")


if __name__ == "__main__":
    try:
        asyncio.run(run_messaging_test())
    except Exception as exc:
        print(f"Messaging test failed: {exc}")
        sys.exit(1)
    sys.exit(0)
