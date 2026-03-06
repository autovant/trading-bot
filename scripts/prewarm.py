"""VPS Cold-Start Pre-Warming

On VPS boot, this script:
1. Loads recent positions, open orders, and agent state from the DB
2. Verifies exchange connectivity
3. Ensures the strategy engine can resume safely
4. Runs a health check gate before accepting new signals

Usage:
    python -m scripts.prewarm            # Run pre-warming checks
    python -m scripts.prewarm --wait 30  # Wait up to 30s for services

Environment:
    DATABASE_URL — PostgreSQL connection string
    EXCHANGE_API_KEY / EXCHANGE_SECRET_KEY — exchange credentials
    NATS_URL — NATS server URL (default: nats://localhost:4222)
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from typing import Any

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("prewarm")


# ── Service readiness checks ─────────────────────────────────────────


async def wait_for_service(
    url: str, label: str, timeout: float = 60,
) -> bool:
    """Poll a URL until it returns 200 or timeout."""
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=5) as client:
        while time.monotonic() - start < timeout:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    logger.info("  ✓ %s is ready", label)
                    return True
            except (httpx.ConnectError, httpx.ReadTimeout):
                pass
            await asyncio.sleep(2)
    logger.error("  ✗ %s did not become ready within %ds", label, timeout)
    return False


async def check_services(timeout: float) -> bool:
    """Verify all critical VPS services are reachable."""
    logger.info("Checking service readiness...")

    services = [
        ("http://localhost:8222", "NATS"),
        ("http://localhost:8080/health", "Execution Service"),
        ("http://localhost:8081/health", "Feed Service"),
        ("http://localhost:8084/health", "Risk Service"),
        ("http://localhost:8086/health", "Signal Engine"),
    ]

    results = await asyncio.gather(
        *[wait_for_service(url, label, timeout) for url, label in services]
    )
    return all(results)


# ── Database pre-load ─────────────────────────────────────────────────


async def prewarm_database() -> dict[str, Any]:
    """Load critical state from the database into memory."""
    logger.info("Pre-warming database state...")

    summary: dict[str, Any] = {
        "positions": 0,
        "open_orders": 0,
        "active_agents": 0,
        "db_connected": False,
    }

    try:
        import asyncpg

        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql://tradingbot:tradingbot@localhost:5432/tradingbot",
        )
        conn = await asyncpg.connect(db_url)
        summary["db_connected"] = True

        # Positions
        positions = await conn.fetch(
            "SELECT * FROM positions WHERE status = 'open'"
        )
        summary["positions"] = len(positions)
        if positions:
            for p in positions:
                logger.info(
                    "  Position: %s %s qty=%.4f entry=%.2f",
                    p.get("symbol", "?"),
                    p.get("side", "?"),
                    float(p.get("quantity", 0)),
                    float(p.get("entry_price", 0)),
                )

        # Open orders
        orders = await conn.fetch(
            "SELECT * FROM orders WHERE status IN ('open', 'partial')"
        )
        summary["open_orders"] = len(orders)
        if orders:
            logger.info("  %d open orders to reconcile", len(orders))

        # Active agents
        agents = await conn.fetch(
            "SELECT id, name, status FROM agents WHERE status IN ('live', 'paper', 'backtesting')"
        )
        summary["active_agents"] = len(agents)
        for a in agents:
            logger.info(
                "  Agent: %s (id=%d, status=%s)",
                a.get("name", "?"),
                a.get("id", 0),
                a.get("status", "?"),
            )

        await conn.close()

    except ImportError:
        logger.warning("asyncpg not installed — skipping DB pre-warm")
    except Exception as e:
        logger.error("Database pre-warm failed: %s", e)

    return summary


# ── Exchange connectivity ─────────────────────────────────────────────


async def check_exchange() -> bool:
    """Verify exchange API is reachable."""
    logger.info("Checking exchange connectivity...")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Try Bybit server time as a connectivity test
            resp = await client.get("https://api.bybit.com/v5/market/time")
            if resp.status_code == 200:
                data = resp.json()
                server_time = data.get("result", {}).get("timeSecond", "?")
                logger.info("  ✓ Exchange reachable (server time: %s)", server_time)
                return True
    except Exception as e:
        logger.error("  ✗ Exchange unreachable: %s", e)
    return False


# ── Health gate ───────────────────────────────────────────────────────


async def publish_health_gate(ready: bool) -> None:
    """Publish readiness status to NATS so other services know when to start."""
    try:
        import nats as nats_lib

        nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
        nc = await nats_lib.connect(nats_url)

        status = "ready" if ready else "warming"
        import json

        await nc.publish(
            "system.health.gate",
            json.dumps({"status": status, "timestamp": time.time()}).encode(),
        )
        logger.info("Published health gate: %s", status)
        await nc.close()
    except ImportError:
        logger.warning("nats-py not installed — skipping health gate publish")
    except Exception as e:
        logger.warning("Failed to publish health gate: %s", e)


# ── Main ──────────────────────────────────────────────────────────────


async def main(wait_timeout: float = 60) -> int:
    logger.info("═══ VPS Cold-Start Pre-Warming ═══")
    logger.info("")

    # 1. Signal that we are warming up
    await publish_health_gate(ready=False)

    # 2. Wait for services
    services_ok = await check_services(wait_timeout)

    # 3. Pre-load DB state
    db_summary = await prewarm_database()

    # 4. Check exchange
    exchange_ok = await check_exchange()

    # 5. Summary
    logger.info("")
    logger.info("═══ Pre-Warm Summary ═══")
    logger.info("  Services ready:  %s", "✓" if services_ok else "✗")
    logger.info("  Database:        %s", "✓" if db_summary["db_connected"] else "✗")
    logger.info("  Positions:       %d", db_summary["positions"])
    logger.info("  Open orders:     %d", db_summary["open_orders"])
    logger.info("  Active agents:   %d", db_summary["active_agents"])
    logger.info("  Exchange:        %s", "✓" if exchange_ok else "✗")

    all_ok = services_ok and db_summary["db_connected"] and exchange_ok

    # 6. Signal readiness
    await publish_health_gate(ready=all_ok)

    if all_ok:
        logger.info("")
        logger.info("✓ Pre-warming complete — system ready for trading")
        return 0
    else:
        logger.warning("")
        logger.warning("⚠ Pre-warming incomplete — review failures above")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VPS cold-start pre-warming")
    parser.add_argument(
        "--wait",
        type=float,
        default=60,
        help="Max seconds to wait for services (default: 60)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(wait_timeout=args.wait)))
