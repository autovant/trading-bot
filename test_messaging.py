"""
Test messaging system functionality.
"""

import asyncio
import sys

from src.config import load_config
from src.messaging import MessagingClient


async def test_messaging():
    """Test NATS messaging system."""
    try:
        # Load configuration
        config = load_config()

        # Create messaging client
        messaging_config = {"servers": config.messaging.servers}
        client = MessagingClient(messaging_config)

        # Connect to NATS
        await client.connect()
        print("Connected to NATS successfully")

        # Test publish
        test_data = {"message": "Hello from test", "timestamp": "2023-01-01T00:00:00Z"}

        await client.publish("test.subject", test_data)
        print("Published test message")

        # Test subscribe
        async def message_handler(data):
            print(f"Received message: {data}")

        subscription = await client.subscribe("test.reply", message_handler)

        # Test request-response
        response = await client.request(
            "test.subject", {"request": "ping"}, timeout=1.0
        )
        if response:
            print(f"Received response: {response}")
        else:
            print("No response received")

        # Keep alive for a bit
        await asyncio.sleep(2)

        # Cleanup
        await subscription.unsubscribe()
        await client.close()
        print("Messaging test completed successfully")

    except Exception as e:
        print(f"Error in messaging test: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(test_messaging())
    sys.exit(exit_code)
