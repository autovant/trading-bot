import logging
from typing import Optional

import aiohttp

from .config import StrategyConfig, TradingBotConfig
from .exchanges.bybit_ws import BybitWebsocketClient
from .database import DatabaseManager
from .exchange import IExchange, create_exchange_client
from .messaging import MessagingClient, MockMessagingClient
from .paper_trader import PaperBroker
from .presets import get_preset_strategies
from .strategy import TradingStrategy

logger = logging.getLogger(__name__)


class Container:
    """
    Dependency Injection Container / Service Locator.
    Manages the lifecycle and wiring of application services.
    """

    def __init__(self, config: TradingBotConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.database: Optional[DatabaseManager] = None
        self.messaging: Optional[MessagingClient] = None
        self.paper_broker: Optional[PaperBroker] = None
        self.exchange: Optional[IExchange] = None
        self.bybit_ws: Optional[BybitWebsocketClient] = None
        self.strategy: Optional[TradingStrategy] = None
        self.run_id: str = "default_run"  # Should be set during init

    async def initialize(self, run_id: str) -> None:
        """Initialize all services."""
        self.run_id = run_id
        self.session = aiohttp.ClientSession()

        # Database
        self.database = DatabaseManager(self.config.database.url)
        await self.database.initialize()

        # Messaging
        messaging_config = {"servers": self.config.messaging.servers}
        try:
            self.messaging = MessagingClient(messaging_config)
            await self.messaging.connect()
        except Exception as e:
            logger.error(
                f"Failed to connect to NATS: {e}. Falling back to MockMessagingClient."
            )
            self.messaging = MockMessagingClient()
            await self.messaging.connect()

        # Paper Broker
        if self.config.app_mode != "live":
            self.paper_broker = PaperBroker(
                config=self.config.paper,
                database=self.database,
                mode=self.config.app_mode,
                run_id=self.run_id,
                initial_balance=self.config.backtesting.initial_balance,
                risk_config=self.config.risk_management,
            )

        # Exchange
        self.exchange = create_exchange_client(
            config=self.config.exchange,
            app_mode=self.config.app_mode,
            paper_broker=self.paper_broker,
        )
        if self.exchange:
            await self.exchange.initialize()

        # Bybit Websocket (Limited Live Ready)
        if (
            self.config.exchange.name == "bybit"
            and self.config.app_mode in ["live", "testnet"]
            and self.messaging
        ):
            self.bybit_ws = BybitWebsocketClient(
                api_key=self.config.exchange.api_key,
                api_secret=self.config.exchange.secret_key,
                messaging=self.messaging,
                testnet=self.config.exchange.testnet,
            )

        # Strategy
        await self._init_strategy()

    async def _init_strategy(self):
        # Load strategies (DB > YAML)
        active_strategies = []
        try:
            db_strategies = await self.database.list_strategies()
            active_db_strategies = [s for s in db_strategies if s.is_active]
            if active_db_strategies:
                for s in active_db_strategies:
                    cfg = StrategyConfig.from_db_row(s)
                    if cfg:
                        active_strategies.append(cfg)
        except Exception as e:
            logger.error(f"Failed to load strategies from DB: {e}")

        # Fallback
        if not active_strategies:
            presets = get_preset_strategies()
            if self.config.strategy.active_strategies:
                for name in self.config.strategy.active_strategies:
                    preset = next((p for p in presets if p.name == name), None)
                    if preset:
                        active_strategies.append(preset)

        self.strategy = TradingStrategy(
            config=self.config,
            exchange=self.exchange,
            database=self.database,
            messaging=self.messaging,
            paper_broker=self.paper_broker,
            run_id=self.run_id,
            strategy_configs=active_strategies,
        )

    async def shutdown(self):
        """Shutdown all services in reverse order."""
        if self.exchange:
            await self.exchange.close()

        if self.messaging:
            await self.messaging.close()  # assuming close method exists or similar

        if self.session:
            await self.session.close()

        logger.info("Container services shutdown complete")
