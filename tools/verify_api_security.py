import asyncio
import sys

import aiohttp

# Configuration
API_URL = "http://localhost:8000"
API_KEY = "secret-key"  # Matching docker-compose default


async def test_endpoint(
    session, method, endpoint, key=None, payload=None, expect_status=200
):
    headers = {}
    if key:
        headers["X-API-KEY"] = key

    url = f"{API_URL}{endpoint}"
    print(
        f"Testing {method} {endpoint} | Key: {'YES' if key else 'NO'} ... ",
        end="",
        flush=True,
    )

    try:
        if method == "GET":
            async with session.get(url, headers=headers) as resp:
                status = resp.status
                text = await resp.text()
        elif method == "POST":
            async with session.post(url, headers=headers, json=payload) as resp:
                status = resp.status
                text = await resp.text()
        elif method == "DELETE":
            async with session.delete(url, headers=headers) as resp:
                status = resp.status
                text = await resp.text()

        if status == expect_status:
            print(f"PASS ({status})")
            return True
        else:
            print(f"FAIL ({status})")
            print(f"  Response: {text[:200]}...")
            return False

    except Exception as e:
        print(f"ERROR: {e}")
        return False


async def main():
    print(f"Verifying API Security at {API_URL}")

    async with aiohttp.ClientSession() as session:
        # 1. Health check (should be public if exists, or 404 if not defined but allowed)
        # We didn't define /health explicitly in api_server.py but FastAPI might give 404, which is fine security-wise.
        # Let's test /api/bot/status which is GET and I didn't protect it.
        await test_endpoint(session, "GET", "/api/bot/status", expect_status=200)

        # 2. Protected Endpoint WITHOUT Key -> Should Fail (403)
        await test_endpoint(session, "POST", "/api/bot/start", expect_status=403)

        # 3. Protected Endpoint WITH WRONG Key -> Should Fail (403)
        await test_endpoint(
            session, "POST", "/api/bot/start", key="wrong-key", expect_status=403
        )

        # 4. Protected Endpoint WITH CORRECT Key -> Should Succeed (200)
        # Note: This will actually try to start the bot.
        # We might want to use a less intrusive endpoint like /api/paper/config (GET) which I protected?
        # Wait, I protected GET /api/paper/config? Yes.
        await test_endpoint(
            session, "GET", "/api/paper/config", key=API_KEY, expect_status=200
        )

        # 5. Protected POST with Key
        # Let's try to update config with same values to test write access
        # First get config
        async with session.get(
            f"{API_URL}/api/paper/config", headers={"X-API-KEY": API_KEY}
        ) as resp:
            if resp.status == 200:
                config = await resp.json()
                await test_endpoint(
                    session,
                    "POST",
                    "/api/paper/config",
                    key=API_KEY,
                    payload=config,
                    expect_status=200,
                )


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
