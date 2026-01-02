import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional



from src.config import TradingBotConfig, get_config
from src.container import Container
from src.database import DatabaseManager
from src.exchange import ExchangeClient
from src.exchanges.bybit_ws import BybitWebsocketClient
from src.logging_config import setup_logging
from src.messaging import MessagingClient
from src.paper_trader import PaperBroker
from src.presets import get_preset_strategies
from src.services.market_data import MarketDataPublisher
from src.services.perps import PerpsService
from src.security.mode_guard import validate_mode_config
from src.state.run_id_store import resolve_run_id
from src.strategy import TradingStrategy

"""
Main entry point for the Trading Bot.

This module orchestrates the trading system, including:
- Initialization of all services (Database, Exchange, Messaging, Strategy)
- Configuration management and hot-reloading
- Main event loop for the trading cycle
- Signal handling for graceful shutdown
"""

def _create_paper_broker(

    config: TradingBotConfig, database: DatabaseManager, run_id: str
) -> PaperBroker:
    """Factory to create a PaperBroker instance."""
    return PaperBroker(
        config=config.paper,
        database=database,
        mode=config.app_mode,
        run_id=run_id,
        initial_balance=config.backtesting.initial_balance,
        risk_config=config.risk_management,
    )


def build_trading_strategy(
    config: TradingBotConfig,
    exchange: ExchangeClient,
    database: DatabaseManager,
    messaging: MessagingClient,
    paper_broker: Optional[PaperBroker],
    run_id: str,
    strategy_configs: List[Any],
) -> TradingStrategy:
    """Factory to create a TradingStrategy instance."""
    return TradingStrategy(
        config=config,
        exchange=exchange,
        database=database,
        messaging=messaging,
        paper_broker=paper_broker,
        run_id=run_id,
        strategy_configs=strategy_configs,
    )


logger = logging.getLogger(__name__)


class TradingEngine:
    """
    Core trading engine that manages the lifecycle of all services.

    Attributes:
        running (bool): Flag indicating if the engine is active.
        config (TradingBotConfig): Current system configuration.
        container (Container): Dependency injection container.
    """

    def __init__(self) -> None:

        self.running = False
        self.config: Optional[TradingBotConfig] = None
        self.exchange: Optional[ExchangeClient] = None
        self.database: Optional[DatabaseManager] = None
        self.messaging: Optional[MessagingClient] = None
        self.strategy: Optional[TradingStrategy] = None
        self.paper_broker: Optional[PaperBroker] = None
        self.perps_service: Optional[PerpsService] = None
        self.market_data_publisher: Optional[MarketDataPublisher] = None
        self.bybit_ws: Optional[BybitWebsocketClient] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.run_id: Optional[str] = None
        self._last_config_mtime: float = 0.0

    async def initialize(self):
        logger.info("Initializing trading engine...")
        try:
            config = get_config()
            setup_logging(config)
            mode_name = (
                "live"
                if config.app_mode == "live"
                else ("testnet" if config.perps.useTestnet else config.app_mode)
            )
            validate_mode_config(
                mode_name=mode_name,
                exchange_testnet=config.exchange.testnet,
                perps_testnet=config.perps.useTestnet,
                exchange_base_url=config.exchange.base_url
                or os.getenv("ZOOMEX_BASE"),
            )

            self._last_config_mtime = Path("config/strategy.yaml").stat().st_mtime

            # Initialize Container
            self.container = Container(config)
            run_id = self.run_id or resolve_run_id(
                prefix=Path(config.config_paths.strategy).stem
            )
            await self.container.initialize(run_id)

            # Bind container services to self for backward compat / ease of access
            self.config = self.container.config
            self.database = self.container.database
            self.messaging = self.container.messaging
            self.paper_broker = self.container.paper_broker
            self.exchange = self.container.exchange
            self.bybit_ws = self.container.bybit_ws
            self.strategy = self.container.strategy
            self.session = self.container.session
            self.run_id = self.container.run_id

            if self.strategy:
                try:
                    await self.strategy.execution_engine.reconcile_startup()
                except Exception as e:
                    logger.error(
                        "Execution reconciliation failed on startup: %s", e, exc_info=True
                    )
                    raise

            if hasattr(self.config, "perps"):
                logger.info("Initializing PerpsService...")
                try:
                    self.perps_service = PerpsService(
                        self.config.perps,
                        self.exchange,
                        trading_config=self.config.trading,
                        crisis_config=self.config.risk_management.crisis_mode,
                        database=self.database,
                        mode_name=self.config.app_mode,
                    )
                    await self.perps_service.initialize()
                    logger.info("PerpsService initialized.")
                except Exception as e:
                    logger.error(f"PerpsService init failed: {e}", exc_info=True)
                    raise

            # Initialize Market Data Publisher
            logger.info("Initializing MarketDataPublisher...")
            self.market_data_publisher = MarketDataPublisher(
                self.config, self.exchange, self.messaging
            )
            await self.market_data_publisher.start()
            logger.info("MarketDataPublisher started.")

            # Start Bybit WS
            if self.bybit_ws:
                self._bybit_ws_task = asyncio.create_task(self.bybit_ws.start())

            # Subscribe to bot control commands
            await self.messaging.subscribe(
                "command.bot.halt", self._handle_halt_command
            )

            logger.info("Trading engine initialized successfully")

        except BaseException as e:
            logger.error(f"Failed to initialize trading engine: {e}", exc_info=True)
            raise

    async def _handle_halt_command(self, msg: Any) -> None:
        """Handle emergency halt command."""
        logger.warning("Received HALT command via NATS")
        if self.perps_service:
            await self.perps_service.halt()

        # Also disable in config to prevent restart
        # We can't easily write to config here without reloading logic interfering,
        # but api_server should have already updated the config file.
        # We just need to ensure we stop trading.
        # PerpsService.halt() sets reconciliation_block_active=True, which blocks entries.

    def signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False


async def main():
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    engine = TradingEngine()

    signal.signal(signal.SIGINT, engine.signal_handler)
    signal.signal(signal.SIGTERM, engine.signal_handler)

    try:
        await engine.initialize()
        await engine.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
