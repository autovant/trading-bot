import asyncio
import logging
import signal
import sys
from pathlib import Path

import aiohttp

from src.config import get_config, TradingBotConfig
from src.database import DatabaseManager
from src.exchange import ExchangeClient
from src.exchange import ExchangeClient
from src.messaging import MessagingClient, MockMessagingClient
from src.strategy import TradingStrategy, db_row_to_strategy_config
from src.paper_trader import PaperBroker
from src.services.perps import PerpsService
from src.presets import get_preset_strategies
from typing import List, Any, Optional

def _create_paper_broker(
    config: TradingBotConfig,
    database: DatabaseManager,
    run_id: str
) -> PaperBroker:
    """Factory to create a PaperBroker instance."""
    return PaperBroker(
        config=config.paper,
        database=database,
        mode=config.app_mode,
        run_id=run_id,
        initial_balance=config.backtesting.initial_balance,
        risk_config=config.risk_management
    )

def build_trading_strategy(
    config: TradingBotConfig,
    exchange: ExchangeClient,
    database: DatabaseManager,
    messaging: MessagingClient,
    paper_broker: Optional[PaperBroker],
    run_id: str,
    strategy_configs: List[Any]
) -> TradingStrategy:
    """Factory to create a TradingStrategy instance."""
    return TradingStrategy(
        config=config,
        exchange=exchange,
        database=database,
        messaging=messaging,
        paper_broker=paper_broker,
        run_id=run_id,
        strategy_configs=strategy_configs
    )





from src.services.market_data import MarketDataPublisher

logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self) -> None:
        self.running = False
        self.config: TradingBotConfig = None
        self.exchange: ExchangeClient = None
        self.database: DatabaseManager = None
        self.messaging: MessagingClient = None
        self.strategy: TradingStrategy = None
        self.paper_broker: PaperBroker = None
        self.perps_service: PerpsService = None
        self.market_data_publisher: MarketDataPublisher = None
        self.session: aiohttp.ClientSession = None
        self.run_id: str = None
        self._last_config_mtime = 0




    async def initialize(self):
        logger.info("Initializing trading engine...")
        try:
            self.config = get_config()
            self._last_config_mtime = Path("config/strategy.yaml").stat().st_mtime

            self.session = aiohttp.ClientSession()

            # Initialize Database
            self.database = DatabaseManager(self.config.database.path)
            await self.database.initialize()

            # Initialize Messaging
            messaging_config = {"servers": self.config.messaging.servers}
            try:
                self.messaging = MessagingClient(messaging_config)
                await self.messaging.connect()
            except Exception as e:
                logger.error(f"Failed to connect to NATS: {e}. Falling back to MockMessagingClient.")
                self.messaging = MockMessagingClient()
                await self.messaging.connect()

            # Initialize PaperBroker if needed
            if self.config.app_mode != "live":
                self.paper_broker = _create_paper_broker(
                    self.config,
                    self.database,
                    self.run_id or "default_run"
                )

            # Initialize Exchange
            self.exchange = ExchangeClient(
                self.config.exchange,
                app_mode=self.config.app_mode,
                paper_broker=self.paper_broker
            )
            
            # Load strategies (DB > YAML)
            active_strategies = []
            
            # Try DB first
            try:
                db_strategies = await self.database.list_strategies()
                active_db_strategies = [s for s in db_strategies if s.is_active]
                
                if active_db_strategies:
                    logger.info(f"Loading {len(active_db_strategies)} active strategies from DB")
                    for s in active_db_strategies:
                        cfg = db_row_to_strategy_config(s)
                        if cfg:
                            active_strategies.append(cfg)
            except Exception as e:
                logger.error(f"Failed to load strategies from DB: {e}")

            # Fallback to YAML if no DB strategies
            if not active_strategies:
                presets = get_preset_strategies()
                if self.config.strategy.active_strategies:
                    for name in self.config.strategy.active_strategies:
                        preset = next((p for p in presets if p.name == name), None)
                        if preset:
                            active_strategies.append(preset)
                            logger.info(f"Activated strategy from YAML: {name}")
                        else:
                            logger.warning(f"Strategy {name} not found in presets.")

            self.strategy = build_trading_strategy(
                self.config,
                self.exchange,
                self.database,
                self.messaging,
                self.paper_broker,
                self.run_id,
                active_strategies
            )

            if hasattr(self.config, 'perps'):
                logger.info("Initializing PerpsService...")
                try:
                    self.perps_service = PerpsService(
                        self.config.perps,
                        self.exchange,
                        trading_config=self.config.trading,
                        crisis_config=self.config.risk_management.crisis_mode,
                    )
                    await self.perps_service.initialize()
                    logger.info("PerpsService initialized.")
                except Exception as e:
                    logger.error(f"PerpsService init failed: {e}", exc_info=True)
                    raise

            # Initialize Market Data Publisher
            logger.info("Initializing MarketDataPublisher...")
            self.market_data_publisher = MarketDataPublisher(
                self.config,
                self.exchange,
                self.messaging
            )
            await self.market_data_publisher.start()
            logger.info("MarketDataPublisher started.")

            # Subscribe to bot control commands
            await self.messaging.subscribe("command.bot.halt", self._handle_halt_command)

            logger.info("Trading engine initialized successfully")

        except BaseException as e:
            logger.error(f"Failed to initialize trading engine: {e}", exc_info=True)
            raise

    async def reload_config_if_changed(self):
        config_path = Path("config/strategy.yaml")

        if not config_path.exists():
            raise FileNotFoundError("Configuration file not found")

        current_mtime = config_path.stat().st_mtime

        if current_mtime > self._last_config_mtime:
            logger.info("Reloading configuration...")
            try:
                new_config = get_config()
                
                # 1. Load strategies from DB (Precedence: DB > YAML)
                active_strategies = []
                try:
                    db_strategies = await self.database.list_strategies()
                    active_db_strategies = [s for s in db_strategies if s.is_active]
                    
                    if active_db_strategies:
                        logger.info(f"Loading {len(active_db_strategies)} active strategies from DB")
                        for s in active_db_strategies:
                            cfg = db_row_to_strategy_config(s)
                            if cfg:
                                active_strategies.append(cfg)
                except Exception as e:
                    logger.error(f"Failed to load strategies from DB during reload: {e}")

                if not active_strategies:
                    presets = get_preset_strategies()
                    if new_config.strategy.active_strategies:
                        for name in new_config.strategy.active_strategies:
                            preset = next((p for p in presets if p.name == name), None)
                            if preset:
                                active_strategies.append(preset)
                                logger.info(f"Activated strategy from YAML: {name}")

                # 2. Re-init PaperBroker if needed
                new_paper_broker = None
                if new_config.app_mode != "live":
                    new_paper_broker = _create_paper_broker(
                        new_config, 
                        self.database, 
                        self.run_id or "default_run"
                    )

                # 3. Re-init Exchange if mode changed or broker changed
                new_exchange = self.exchange
                mode_changed = new_config.app_mode != self.config.app_mode
                
                if mode_changed:
                    logger.info(f"App mode changed to {new_config.app_mode}. Re-initializing Exchange...")
                    if self.exchange:
                        await self.exchange.close()
                    new_exchange = ExchangeClient(
                        new_config.exchange, 
                        app_mode=new_config.app_mode, 
                        paper_broker=new_paper_broker
                    )
                    await new_exchange.initialize()
                elif new_paper_broker and self.exchange:
                    # If we have a new paper broker but mode didn't change (e.g. config update),
                    # we should update the exchange's broker reference if it's in paper mode.
                    # But ExchangeClient doesn't expose a setter. 
                    # For safety, if we have a new paper broker, let's re-init exchange to be safe.
                    # Or we can just assume ExchangeClient holds a reference? 
                    # Actually, ExchangeClient uses paper_broker for order execution.
                    # If we replace paper_broker, we MUST update ExchangeClient.
                    if new_config.app_mode != "live":
                         logger.info("Paper broker updated. Re-initializing Exchange...")
                         if self.exchange:
                            await self.exchange.close()
                         new_exchange = ExchangeClient(
                            new_config.exchange, 
                            app_mode=new_config.app_mode, 
                            paper_broker=new_paper_broker
                        )
                         await new_exchange.initialize()

                # 4. Build new Strategy
                new_strategy = build_trading_strategy(
                    new_config,
                    new_exchange,
                    self.database,
                    self.messaging,
                    new_paper_broker,
                    self.run_id,
                    active_strategies
                )

                # 5. Atomic Swap
                self.config = new_config
                self.exchange = new_exchange
                self.paper_broker = new_paper_broker
                self.strategy = new_strategy
                self._last_config_mtime = current_mtime
                
                logger.info("Configuration reloaded successfully")

            except Exception as e:
                logger.error(f"Failed to reload configuration: {e}")
                # Do not update state on error

    async def run(self):
        self.running = True
        logger.info("Starting trading engine...")

        try:
            while self.running:
                await self.reload_config_if_changed()

                await self.trading_cycle()

                await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Trading engine error: {e}")
            raise
        finally:
            await self.shutdown()

    async def trading_cycle(self):
        try:
            if self.perps_service:
                await self.perps_service.run_cycle()

            if self.strategy:
                await self.strategy.update_market_data()
                await self.strategy.run_analysis()
        except Exception as e:
            logger.error(f"Trading cycle error: {e}")

    async def shutdown(self):
        logger.info("Shutting down trading engine...")
        self.running = False

        if self.market_data_publisher:
            await self.market_data_publisher.stop()

        if self.strategy:
            await self.strategy.close_all_positions()

        if self.exchange:
            await self.exchange.close()

        if self.database:
            await self.database.close()

        if self.messaging:
            await self.messaging.close()

        if self.session:
            await self.session.close()

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
