import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.middleware.error_handler import AppError, global_exception_handler
from src.api.middleware.rate_limit import (
    RateLimitExceeded,
    limiter,
    rate_limit_exceeded_handler,
)
from prometheus_client import make_asgi_app
import src.metrics # Initialize metrics
from src.api.routes.backtest import backtest_router
from src.api.routes.market import get_db, get_exchange, market_router
from src.api.routes.strategy import get_db as get_db_strategy
from src.api.routes.strategy import strategy_router
from src.api.routes.system import get_messaging as get_messaging_fn
from src.api.routes.system import system_router
from src.config import TradingBotConfig, get_config
from src.database import DatabaseManager
from src.exchange import ExchangeClient, create_exchange_client
from src.messaging import MessagingClient
from src.paper_trader import PaperBroker

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Global state container
class AppState:
    config: Optional[TradingBotConfig] = None
    database: Optional[DatabaseManager] = None
    messaging: Any = None
    exchange: Optional[ExchangeClient] = None
    rollup_task: Optional[asyncio.Task] = None


_state = AppState()


# Dependency providers
async def get_db_dependency() -> DatabaseManager:
    if not _state.database:
        raise RuntimeError("Database not initialized")
    return _state.database


async def get_exchange_dependency() -> ExchangeClient:
    if not _state.exchange:
        # In some modes exchange might not be needed?
        # But for market_router it is.
        # Making it non-optional here implies strict dependency.
        raise RuntimeError("Exchange not initialized")
    return _state.exchange


def get_messaging_dependency():
    return _state.messaging


class MockMessagingClient:
    async def connect(self, timeout: float = 1.0):
        logger.warning("Using MockMessagingClient (NATS unavailable)")

    async def close(self):
        pass

    async def publish(self, subject: str, message: Dict[str, Any]):
        logger.info(f"Mock publish to {subject}: {message}")

    async def subscribe(self, subject: str, callback: Any):
        logger.info(f"Mock subscribe to {subject}")
        return None

    async def request(
        self, subject: str, message: Dict[str, Any], timeout: float = 1.0
    ):
        return None


async def _ensure_messaging():
    if _state.messaging is None:
        config = get_config()
        try:
            real_client = MessagingClient({"servers": config.messaging.servers})
            await real_client.connect()
            _state.messaging = real_client
        except Exception as e:
            logger.error(
                f"Failed to connect to NATS: {e}. Falling back to MockMessagingClient."
            )
            _state.messaging = MockMessagingClient()
            await _state.messaging.connect()
    return _state.messaging


@asynccontextmanager
async def lifespan(app: FastAPI):
    _state.config = get_config()

    _state.database = DatabaseManager(_state.config.database)
    await _state.database.initialize()

    await _ensure_messaging()

    paper_broker = None
    if _state.config.app_mode != "live":
        paper_broker = PaperBroker(
            config=_state.config.paper,
            database=_state.database,
            mode=_state.config.app_mode,
            run_id="api_server",
            initial_balance=_state.config.backtesting.initial_balance,
            risk_config=_state.config.risk_management,
        )

    _state.exchange = create_exchange_client(
        config=_state.config.exchange,
        app_mode=_state.config.app_mode,
        paper_broker=paper_broker,
    )
    await _state.exchange.initialize()

    # Start background tasks
    # _state.rollup_task = asyncio.create_task(_pnl_rollup_loop())
    # TODO: Move cleanup loop to a service

    yield

    # Cleanup
    if _state.messaging:
        await _state.messaging.close()

    if _state.exchange:
        await _state.exchange.close()

    if _state.database:
        await _state.database.close()


app = FastAPI(title="Trading Bot API", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency Overrides
# We use this to wire up the router dependencies to our global state
app.dependency_overrides[get_db] = get_db_dependency
app.dependency_overrides[get_exchange] = get_exchange_dependency
app.dependency_overrides[get_db_strategy] = get_db_dependency
app.dependency_overrides[get_messaging_fn] = get_messaging_dependency


# Include Routers
app.include_router(system_router)
app.include_router(market_router)
app.include_router(strategy_router)
app.include_router(backtest_router)

# Middleware Registration
# Imports moved to top


# Register Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Register Global Exception Handler
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(AppError, global_exception_handler)
app.add_exception_handler(StarletteHTTPException, global_exception_handler)
app.add_exception_handler(RequestValidationError, global_exception_handler)


app.mount("/metrics", make_asgi_app())
