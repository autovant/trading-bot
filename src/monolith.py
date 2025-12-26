import asyncio
import logging
import os
import sys

import uvicorn

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("monolith")

# -----------------------------------------------------------------------------
# 1. Environment Overrides for No-Docker Mode
# -----------------------------------------------------------------------------
# Use absolute path for DB to avoid CWD issues
db_path = os.path.abspath("data/trading.db")
os.environ["DB_URL"] = f"sqlite:///{db_path}"
# Use in-memory messaging
os.environ["NATS_URL"] = "memory://"
# Ensure API Key is set
if not os.getenv("API_KEY"):
    os.environ["API_KEY"] = "secret-key"

logger.info("Starting Trading Bot Monolith (No-Docker Mode)...")
logger.info(f"Database: {os.environ['DB_URL']}")
logger.info(f"Messaging: {os.environ['NATS_URL']}")

# -----------------------------------------------------------------------------
# 2. Imports (must be after env vars if they read config at module level)
# -----------------------------------------------------------------------------
try:
    from src.api_server import app as api_app
    from src.main import TradingEngine
    from src.services.execution import ExecutionService
    from src.services.feed import FeedService
    from src.services.reporter import ReporterService
    from src.services.risk import RiskService
except ImportError as e:
    logger.error(f"Failed to import services: {e}")
    sys.exit(1)

# -----------------------------------------------------------------------------
# 3. Orchestration
# -----------------------------------------------------------------------------


async def main():
    # Instantiate Services
    services = [
        FeedService(),
        ExecutionService(),
        RiskService(),
        ReporterService(),
    ]

    # Start Services (Background Tasks)
    for service in services:
        logger.info(f"Starting Service: {service.name}...")
        await service.on_startup()

    # Start Trading Engine (Main Loop)
    engine = TradingEngine()
    await engine.initialize()
    # Run engine in background task (it loop forever)
    asyncio.create_task(engine.run())
    logger.info("Trading Engine started.")

    # Start API Server
    # Note: We run uvicorn programmatically to keep control of the loop.
    # We must bind to 0.0.0.0 or localhost.
    config = uvicorn.Config(api_app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    logger.info("Monolith is ready. API running on port 8000.")
    logger.info("Press Ctrl+C to stop.")

    try:
        await server.serve()
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down...")
        # Shutdown in reverse order
        await engine.shutdown()
        for service in reversed(services):
            await service.on_shutdown()


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
