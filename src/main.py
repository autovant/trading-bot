"""
Main trading engine with hot-reload configuration support.
"""

import asyncio
import signal
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, cast
import logging

from prometheus_client import start_http_server

from .config import TradingBotConfig, reload_config, get_config
from .strategy import TradingStrategy
from .exchange import ExchangeClient, Mode
from .database import DatabaseManager
from .messaging import MessagingClient
from .metrics import TRADING_MODE
from .paper_trader import PaperBroker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/trading.log"), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


class TradingEngine:
    """Main trading engine with configuration hot-reload."""

    def __init__(self):
        self.config: Optional[TradingBotConfig] = None
        self.strategy: Optional[TradingStrategy] = None
        self.exchange: Optional[ExchangeClient] = None
        self.database: Optional[DatabaseManager] = None
        self.messaging: Optional[MessagingClient] = None
        self.paper_broker: Optional[PaperBroker] = None
        self.shadow_broker: Optional[PaperBroker] = None
        self.running = False
        self._last_config_mtime = 0
        self.run_id: Optional[str] = None

    async def initialize(self):
        """Initialize all components."""
        try:
            # Load configuration
            self.config = get_config()
            self.run_id = (
                f"{self.config.app_mode}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                f"-{uuid.uuid4().hex[:6]}"
            )

            # Start Prometheus metrics server
            start_http_server(8000)
            for candidate in ("live", "paper", "replay"):
                TRADING_MODE.labels(service="engine", mode=candidate).set(
                    1 if candidate == self.config.app_mode else 0
                )

            # Initialize database
            self.database = DatabaseManager(self.config.database.path)
            await self.database.initialize()

            # Initialize messaging
            messaging_config = {
                "servers": (
                    self.config.messaging.servers
                    if hasattr(self.config, "messaging")
                    else ["nats://localhost:4222"]
                )
            }
            self.messaging = MessagingClient(messaging_config)
            await self.messaging.connect()

            # Initialise paper/shadow brokers if required
            if self.config.app_mode in ("paper", "replay"):
                self.paper_broker = PaperBroker(
                    config=self.config.paper,
                    database=self.database,
                    mode=cast(Mode, self.config.app_mode),
                    run_id=self.run_id,
                    initial_balance=self.config.trading.initial_capital,
                    risk_config=self.config.risk_management,
                )
            else:
                self.paper_broker = None

            if self.config.app_mode == "live" and getattr(
                self.config, "shadow_paper", False
            ):
                self.shadow_broker = PaperBroker(
                    config=self.config.paper,
                    database=self.database,
                    mode="paper",
                    run_id=f"shadow-{self.run_id}",
                    initial_balance=self.config.trading.initial_capital,
                    risk_config=self.config.risk_management,
                )
            else:
                self.shadow_broker = None

            # Initialize exchange client
            self.exchange = ExchangeClient(
                self.config.exchange,
                app_mode=cast(Mode, self.config.app_mode),
                paper_broker=self.paper_broker,
                shadow_broker=self.shadow_broker,
            )
            await self.exchange.initialize()

            # Initialize strategy
            self.strategy = TradingStrategy(
                config=self.config,
                exchange=self.exchange,
                database=self.database,
                messaging=self.messaging,
                paper_broker=self.paper_broker,
                run_id=self.run_id or "",
            )

            logger.info("Trading engine initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize trading engine: {e}")
            raise

    async def reload_config_if_changed(self):
        """Reload configuration if file has changed."""
        config_path = Path("config/strategy.yaml")

        if not config_path.exists():
            raise FileNotFoundError("Configuration file not found")

        current_mtime = config_path.stat().st_mtime

        if current_mtime > self._last_config_mtime:
            logger.info("Reloading configuration...")
            self.config = reload_config()
            self._last_config_mtime = current_mtime

            # Update strategy config if already initialized
            if self.strategy:
                self.strategy.config = self.config

    async def run(self):
        """Main trading loop."""
        self.running = True
        logger.info("Starting trading engine...")

        try:
            while self.running:
                # Check for config changes
                await self.reload_config_if_changed()

                # Execute trading cycle
                await self.trading_cycle()

                # Wait before next cycle
                await asyncio.sleep(60)  # 1 minute cycle

        except Exception as e:
            logger.error(f"Trading engine error: {e}")
            raise
        finally:
            await self.shutdown()

    async def trading_cycle(self):
        """Execute one trading cycle."""
        if not self.strategy:
            return
        try:
            # Update market data
            await self.strategy.update_market_data()

            # Analyze all symbols
            await self.strategy.run_analysis()
        except Exception as e:
            logger.error(f"Trading cycle error: {e}")

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down trading engine...")
        self.running = False

        if self.strategy:
            await self.strategy.close_all_positions()

        if self.exchange:
            await self.exchange.close()

        if self.database:
            await self.database.close()

        if self.messaging:
            await self.messaging.close()

    def signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False


async def main():
    """Main entry point."""
    # Create logs directory
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    engine = TradingEngine()

    # Setup signal handlers
    signal.signal(signal.SIGINT, engine.signal_handler)
    signal.signal(signal.SIGTERM, engine.signal_handler)

    try:
        await engine.initialize()
        await engine.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
