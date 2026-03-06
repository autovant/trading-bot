import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.middleware.auth import APIKeyMiddleware
from src.api.middleware.error_handler import AppError, global_exception_handler
from src.api.middleware.rate_limit import (
    RateLimitExceeded,
    limiter,
    rate_limit_exceeded_handler,
)
from src.api.routes.agents import agents_router
from src.api.routes.agents import get_db as get_db_agents
from src.api.routes.agents import get_messaging as get_messaging_agents
from src.api.routes.auth import auth_router
from src.api.routes.backtest import backtest_router
from src.api.routes.backtest import get_db as get_db_backtest
from src.api.routes.data import data_router
from src.api.routes.intelligence import get_db as get_db_intelligence
from src.api.routes.intelligence import get_exchange as get_exchange_intelligence
from src.api.routes.intelligence import intelligence_router
from src.api.routes.market import get_db, get_exchange, market_router
from src.api.routes.notifications import get_db as get_db_notifications
from src.api.routes.notifications import notifications_router
from src.api.routes.portfolio import get_db as get_db_portfolio
from src.api.routes.portfolio import portfolio_router
from src.api.routes.presets import presets_router
from src.api.routes.risk import get_db as get_db_risk
from src.api.routes.risk import risk_router
from src.api.routes.signals import get_db as get_db_signals
from src.api.routes.signals import signals_router
from src.api.routes.strategy import get_db as get_db_strategy
from src.api.routes.strategy import strategy_router
from src.api.routes.system import get_messaging as get_messaging_fn
from src.api.routes.system import system_router
from src.api.routes.vault import get_db as get_db_vault
from src.api.routes.vault import vault_router
from src.api.ws import websocket_handler, ws_manager
from src.config import TradingBotConfig, get_config
from src.database import DatabaseManager
from src.exchange import ExchangeClient, create_exchange_client
from src.logging_config import CorrelationIdMiddleware
from src.messaging import MessagingClient, MockMessagingClient
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
    try:
        await _state.exchange.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize exchange: {e}. API will have limited functionality.")
        # Don't crash - allow server to start with limited functionality

    # Start background tasks
    # Start WebSocket heartbeat and NATS bridge
    await ws_manager.start_heartbeat()
    if _state.messaging:
        await ws_manager.start_nats_bridge(_state.messaging)

    yield

    # Cleanup
    await ws_manager.stop_heartbeat()
    await ws_manager.stop_nats_bridge()

    if _state.messaging:
        await _state.messaging.close()

    if _state.exchange:
        await _state.exchange.close()

    if _state.database:
        await _state.database.close()


app = FastAPI(title="Trading Bot API", lifespan=lifespan)

# CORS — configurable origins via CORS_ORIGINS env var
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation ID middleware
app.add_middleware(CorrelationIdMiddleware)

# Auth middleware
app.add_middleware(APIKeyMiddleware)

# Dependency Overrides
# We use this to wire up the router dependencies to our global state
app.dependency_overrides[get_db] = get_db_dependency
app.dependency_overrides[get_exchange] = get_exchange_dependency
app.dependency_overrides[get_db_strategy] = get_db_dependency
app.dependency_overrides[get_messaging_fn] = get_messaging_dependency
app.dependency_overrides[get_db_vault] = get_db_dependency
app.dependency_overrides[get_db_backtest] = get_db_dependency
app.dependency_overrides[get_db_agents] = get_db_dependency
app.dependency_overrides[get_messaging_agents] = get_messaging_dependency
app.dependency_overrides[get_db_signals] = get_db_dependency
app.dependency_overrides[get_db_risk] = get_db_dependency
app.dependency_overrides[get_db_notifications] = get_db_dependency
app.dependency_overrides[get_db_portfolio] = get_db_dependency
app.dependency_overrides[get_db_intelligence] = get_db_dependency
app.dependency_overrides[get_exchange_intelligence] = get_exchange_dependency


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "api-server"}


# Include Routers
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(market_router)
app.include_router(strategy_router)
app.include_router(backtest_router)
app.include_router(vault_router)
app.include_router(agents_router)
app.include_router(signals_router)
app.include_router(risk_router)
app.include_router(data_router)
app.include_router(presets_router)
app.include_router(notifications_router)
app.include_router(portfolio_router)
app.include_router(intelligence_router)

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

# --- WebSocket endpoint using ws_manager ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket_handler(websocket, ws_manager)

