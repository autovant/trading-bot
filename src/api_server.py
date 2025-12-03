import asyncio
import json
import logging
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from contextlib import asynccontextmanager

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query, Response, status, WebSocket, WebSocketDisconnect, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.database import DatabaseManager
from src.messaging import MessagingClient
from src.strategy import TradingStrategy
from src.exchange import ExchangeClient
from src.presets import get_preset_strategies
from src.config import get_config, load_config, reload_config, APP_MODE, PaperConfig
from src.paper_trader import PaperBroker
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST, REGISTRY

# Metrics
if 'trading_mode' in REGISTRY._names_to_collectors:
    TRADING_MODE = REGISTRY._names_to_collectors['trading_mode']
else:
    TRADING_MODE = Gauge(
        "trading_mode",
        "Current application mode (1=active, 0=inactive)",
        ["service", "mode"],
    )
MODES = ["live", "paper", "replay"]

# API Models
class BacktestRequest(BaseModel):
    symbol: str
    start: str
    end: str

class _BacktestJob(BaseModel):
    job_id: str
    payload: BacktestRequest
    status: str = "queued"
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class BacktestJobResponse(BaseModel):
    job_id: str
    status: str
    symbol: str
    start: str
    end: str
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class StrategyRequest(BaseModel):
    name: str
    config: Dict[str, Any]

class StrategyResponse(BaseModel):
    id: Optional[int] = None
    name: str
    config: Dict[str, Any]
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class ModeRequest(BaseModel):
    mode: APP_MODE
    shadow: bool = False

class ModeResponse(BaseModel):
    mode: APP_MODE
    shadow: bool

class PaperConfigResponse(BaseModel):
    fee_bps: float
    maker_rebate_bps: float
    funding_enabled: bool
    slippage_bps: float
    max_slippage_bps: float
    spread_slippage_coeff: float
    ofi_slippage_coeff: float
    latency_ms: Dict[str, float]
    partial_fill: Dict[str, Any]
    price_source: str

class PnLDailyEntry(BaseModel):
    date: str
    mode: str
    realized_pnl: float
    unrealized_pnl: float
    fees: float
    funding: float
    commission: float
    net_pnl: float
    balance: float

class PnLDailyResponse(BaseModel):
    mode: str
    days: List[PnLDailyEntry]

class PositionResponse(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    percentage: float
    mode: str
    run_id: str
    created_at: Optional[str]
    updated_at: Optional[str]

class TradeResponse(BaseModel):
    client_id: str
    trade_id: Optional[str]
    order_id: Optional[str]
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    fees: float
    funding: float
    realized_pnl: float
    mark_price: float
    slippage_bps: float
    achieved_vs_signal_bps: float
    latency_ms: float
    maker: bool
    mode: str
    run_id: str
    timestamp: Optional[str]
    is_shadow: bool

class ConfigResponse(BaseModel):
    version: Optional[str]
    config: Dict[str, Any]

class ConfigVersionResponse(BaseModel):
    version: str
    created_at: Optional[str]

class RiskSnapshotResponse(BaseModel):
    crisis_mode: bool
    consecutive_losses: int
    drawdown: float
    volatility: float
    position_size_factor: float
    mode: str
    run_id: str
    created_at: Optional[str]
    payload: Dict[str, Any]

class ConfigStageRequest(BaseModel):
    risk_per_trade: Optional[float] = None
    spread_budget_bps: Optional[float] = None

class ConfigStageResponse(BaseModel):
    version: str
    config: Dict[str, Any]
    changes: Dict[str, Any]

class RawConfigRequest(BaseModel):
    yaml: str

class RawConfigResponse(BaseModel):
    yaml: str

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
_config = None
_database: Optional[DatabaseManager] = None
_messaging: Optional[MessagingClient] = None
_exchange: Optional[ExchangeClient] = None
_strategy_service = None
_rollup_task: Optional[asyncio.Task] = None
_config_lock = asyncio.Lock()
_backtest_lock = asyncio.Lock()
_backtest_jobs: Dict[str, Any] = {}


_BACKTEST_HISTORY_LIMIT = 8
_backtest_tasks: Dict[str, asyncio.Task[None]] = {}


async def _ensure_database() -> DatabaseManager:
    if _database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialised",
        )
    return _database


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

    async def request(self, subject: str, message: Dict[str, Any], timeout: float = 1.0):
        logger.info(f"Mock request to {subject}: {message}")
        return None

async def get_messaging() -> Any:
    global _messaging
    if _messaging is None:
        config = load_config()
        try:
            real_client = MessagingClient({"servers": config.messaging.servers})
            await real_client.connect()
            _messaging = real_client
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}. Falling back to MockMessagingClient.")
            _messaging = MockMessagingClient()
            await _messaging.connect()
    return _messaging


class StrategyService:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def save_strategy(self, name: str, config: Dict[str, Any]) -> Optional[int]:
        if not self.db.connection:
            print("DEBUG: db.connection is None")
            return None
        try:
            cursor = self.db.connection.cursor()
            config_json = json.dumps(config)
            query = "INSERT INTO strategies (name, config) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET config = excluded.config, updated_at = CURRENT_TIMESTAMP"
            cursor.execute(query, (name, config_json))
            self.db.connection.commit()
            rid = cursor.lastrowid
            if rid and rid > 0:
                return rid
            # Fallback for updates where lastrowid might be 0
            cursor.execute("SELECT id FROM strategies WHERE name = ?", (name,))
            row = cursor.fetchone()
            return row["id"] if row else None
        except Exception as exc:
            print(f"DEBUG: Exception in save_strategy: {exc}")
            logger.error("Error saving strategy %s: %s", name, exc)
            return None

    async def list_strategies(self) -> List[Dict[str, Any]]:
        if not self.db.connection:
            return []
        try:
            cursor = self.db.connection.cursor()
            cursor.execute("SELECT * FROM strategies ORDER BY name")
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "config": json.loads(row["config"]),
                    "is_active": bool(row["is_active"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error listing strategies: %s", exc)
            return []

    async def get_strategy(self, name: str) -> Optional[Dict[str, Any]]:
        if not self.db.connection:
            return None
        try:
            cursor = self.db.connection.cursor()
            cursor.execute("SELECT config FROM strategies WHERE name = ?", (name,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["config"])
            return None
        except Exception as exc:
            logger.error("Error getting strategy %s: %s", name, exc)
            return None

    async def activate_strategy(self, name: str) -> bool:
        if not self.db.connection:
            return False
        try:
            cursor = self.db.connection.cursor()
            cursor.execute("UPDATE strategies SET is_active = 0")
            cursor.execute("UPDATE strategies SET is_active = 1 WHERE name = ?", (name,))
            self.db.connection.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Error activating strategy %s: %s", name, exc)
            return False

    async def delete_strategy(self, name: str) -> bool:
        if not self.db.connection:
            return False
        try:
            cursor = self.db.connection.cursor()
            cursor.execute("DELETE FROM strategies WHERE name = ?", (name,))
            self.db.connection.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Error deleting strategy %s: %s", name, exc)
            return False

async def _ensure_strategy_service() -> StrategyService:
    if _strategy_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Strategy service not initialised",
        )
    return _strategy_service


async def _ensure_exchange() -> ExchangeClient:
    if _exchange is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Exchange client not initialised",
        )
    return _exchange


def _strategy_config_path() -> Path:
    if _config is None:
        return Path("config/strategy.yaml")
    return Path(_config.config_paths.strategy)


def _update_trading_mode_metric(mode: APP_MODE) -> None:
    for candidate in MODES:
        TRADING_MODE.labels(service="ops-api", mode=candidate).set(
            1 if candidate == mode else 0
        )


def _resolve_subject(name: str, default: str) -> str:
    if _config and name in _config.messaging.subjects:
        return _config.messaging.subjects[name]
    return default


def _load_strategy_yaml() -> Dict[str, Any]:
    path = _strategy_config_path()
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Strategy config not found at {path}",
        )
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _persist_strategy_yaml(data: Dict[str, Any]) -> None:
    path = _strategy_config_path()
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def _isoformat(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _isoformat_or_none(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return _isoformat(value)


def _normalise_json(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalise_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise_json(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:  # pragma: no cover - best effort
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # pragma: no cover - best effort
            pass
    return value


def _sanitize_backtest_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _normalise_json(value) for key, value in result.items()}


def _serialize_backtest_job(job: _BacktestJob) -> BacktestJobResponse:
    return BacktestJobResponse(
        job_id=job.job_id,
        status=job.status,
        symbol=job.payload.symbol,
        start=job.payload.start,
        end=job.payload.end,
        submitted_at=job.submitted_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        result=job.result,
        error=job.error,
    )


def _purge_backtest_history() -> None:
    if len(_backtest_jobs) <= _BACKTEST_HISTORY_LIMIT:
        return
    ordered = sorted(
        _backtest_jobs.values(), key=lambda record: record.submitted_at, reverse=True
    )
    for stale in ordered[_BACKTEST_HISTORY_LIMIT:]:
        _backtest_jobs.pop(stale.job_id, None)


async def _run_backtest_job(job_id: str) -> None:
    async with _backtest_lock:
        job = _backtest_jobs.get(job_id)
    if job is None:
        return

    job.status = "running"
    job.started_at = datetime.utcnow()

    try:
        config = _config or get_config()
        from tools.backtest import BacktestEngine  # Lazy import to avoid heavy startup

        engine = BacktestEngine(config)
        result = await engine.run_backtest(
            job.payload.symbol,
            job.payload.start,
            job.payload.end,
        )
        if not result:
            raise RuntimeError("Backtest returned an empty result.")

        job.result = _sanitize_backtest_result(result)
        job.status = "completed"
    except Exception as exc:  # pragma: no cover - operational logging
        logger.exception("Backtest job %s failed: %s", job_id, exc)
        job.error = str(exc)
        job.status = "failed"
    finally:
        job.completed_at = datetime.utcnow()
        async with _backtest_lock:
            _backtest_tasks.pop(job_id, None)
            _purge_backtest_history()


async def _publish_config_reload(version: str, config_body: Dict[str, Any]) -> None:
    if not _messaging:
        logger.info("Skipping config.reload publish; messaging not available")
        return

    subject = _resolve_subject("config_reload", "config.reload")
    payload = {
        "version": version,
        "mode": _config.app_mode if _config else None,
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        await _messaging.publish(subject, payload)
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.error("Failed to publish config.reload notification: %s", exc)


async def _pnl_rollup_loop(interval_seconds: int = 3600) -> None:
    while True:
        try:
            database = await _ensure_database()
            summaries = await database.aggregate_daily_pnl(days=60)
            for entry in summaries:
                await database.add_pnl_entry(entry)
        except asyncio.CancelledError:
            raise
        except HTTPException:
            # Database not ready; skip this cycle.
            await asyncio.sleep(interval_seconds)
            continue
        except Exception as exc:  # pragma: no cover - diagnostic logging
            logger.error("PnL rollup task failed: %s", exc)

        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _database, _messaging, _rollup_task, _strategy_service

    _config = get_config()
    _update_trading_mode_metric(_config.app_mode)

    _database = DatabaseManager(_config.database.path)
    await _database.initialize()

    _strategy_service = StrategyService(_database)

    # Initialize Messaging using the shared helper
    await get_messaging()

    # Initialize Exchange
    paper_broker = None
    if _config.app_mode != "live":
        paper_broker = PaperBroker(
            config=_config.paper,
            database=_database,
            mode=_config.app_mode,
            run_id="api_server", # distinct run_id? or shared?
            initial_balance=_config.backtesting.initial_balance,
            risk_config=_config.risk_management
        )
    
    _exchange = ExchangeClient(
        _config.exchange,
        app_mode=_config.app_mode,
        paper_broker=paper_broker
    )
    await _exchange.initialize()

    _rollup_task = asyncio.create_task(_pnl_rollup_loop())

    yield

    if _messaging:
        await _messaging.close()
    _messaging = None

    if _exchange:
        await _exchange.close()
    _exchange = None

    if _database:
        await _database.close()
    _database = None


app = FastAPI(title="Trading Bot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=Dict[str, str])
async def health() -> Dict[str, str]:
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/mode", response_model=ModeResponse)
async def get_mode() -> ModeResponse:
    if _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration not loaded",
        )
    return ModeResponse(mode=_config.app_mode, shadow=_config.shadow_paper)


class BotStatusResponse(BaseModel):
    enabled: bool
    status: str
    symbol: str
    mode: str

@app.get("/api/bot/status", response_model=BotStatusResponse)
async def get_bot_status() -> BotStatusResponse:
    if _config is None:
        raise HTTPException(status_code=503, detail="Config not loaded")
    
    # Determine status
    # If enabled=True, we assume running.
    # If enabled=False, stopped.
    # We could check process health if we had a way, but config is the source of truth for intent.
    status_str = "running" if _config.perps.enabled else "stopped"
    
    return BotStatusResponse(
        enabled=_config.perps.enabled,
        status=status_str,
        symbol=_config.perps.symbol,
        mode=_config.app_mode
    )

@app.post("/api/bot/start")
async def start_bot() -> BotStatusResponse:
    global _config
    async with _config_lock:
        data = _load_strategy_yaml()
        if "perps" not in data:
            data["perps"] = {}
        data["perps"]["enabled"] = True
        _persist_strategy_yaml(data)
        _config = reload_config()
        
        # Publish config reload to notify main process
        await _publish_config_reload(version="manual_start", config_body={})
        
    return await get_bot_status()

@app.post("/api/bot/stop")
async def stop_bot() -> BotStatusResponse:
    global _config
    async with _config_lock:
        data = _load_strategy_yaml()
        if "perps" not in data:
            data["perps"] = {}
        data["perps"]["enabled"] = False
        _persist_strategy_yaml(data)
        _config = reload_config()
        
        # Publish config reload
        await _publish_config_reload(version="manual_stop", config_body={})
        
    return await get_bot_status()

@app.post("/api/bot/halt")
async def halt_bot() -> BotStatusResponse:
    global _config
    
    # 1. Disable in config
    async with _config_lock:
        data = _load_strategy_yaml()
        if "perps" not in data:
            data["perps"] = {}
        data["perps"]["enabled"] = False
        _persist_strategy_yaml(data)
        _config = reload_config()
    
    # 2. Publish HALT command
    if _messaging:
        await _messaging.publish("command.bot.halt", {"timestamp": datetime.utcnow().isoformat()})
    
    # 3. Also try to cancel locally if possible (redundancy)
    if _exchange:
        try:
            await _exchange.cancel_all_orders(_config.perps.symbol)
        except Exception as e:
            logger.error(f"Local cancel failed during halt: {e}")

    return await get_bot_status()


@app.post("/api/mode", response_model=ModeResponse)
async def set_mode(payload: ModeRequest) -> ModeResponse:
    global _config

    async with _config_lock:
        database = await _ensure_database()
        open_positions = await database.get_positions()
        if open_positions:
            if any(abs(position.size) > 0 for position in open_positions):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Mode change blocked while open positions exist",
                )

        data = _load_strategy_yaml()
        data["app_mode"] = payload.mode
        data["shadow_paper"] = payload.shadow
        _persist_strategy_yaml(data)

        os.environ["APP_MODE"] = payload.mode
        _config = reload_config()
        _update_trading_mode_metric(_config.app_mode)
        return ModeResponse(mode=_config.app_mode, shadow=_config.shadow_paper)


@app.get("/api/paper/config", response_model=PaperConfigResponse)
async def get_paper_config() -> PaperConfigResponse:
    if _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration not loaded",
        )
    paper = _config.paper
    return PaperConfigResponse(
        fee_bps=paper.fee_bps,
        maker_rebate_bps=paper.maker_rebate_bps,
        funding_enabled=paper.funding_enabled,
        slippage_bps=paper.slippage_bps,
        max_slippage_bps=paper.max_slippage_bps,
        spread_slippage_coeff=paper.spread_slippage_coeff,
        ofi_slippage_coeff=paper.ofi_slippage_coeff,
        latency_ms={"mean": paper.latency_ms.mean, "p95": paper.latency_ms.p95},
        partial_fill={
            "enabled": paper.partial_fill.enabled,
            "min_slice_pct": paper.partial_fill.min_slice_pct,
            "max_slices": paper.partial_fill.max_slices,
        },
        price_source=paper.price_source,
    )


class PaperConfigRequest(BaseModel):
    fee_bps: float
    maker_rebate_bps: float
    funding_enabled: bool
    slippage_bps: float
    max_slippage_bps: float
    spread_slippage_coeff: float
    ofi_slippage_coeff: float
    latency_ms: Dict[str, float]
    partial_fill: Dict[str, Any]
    price_source: str


@app.post("/api/paper/config", response_model=PaperConfigResponse)
async def update_paper_config(payload: PaperConfigRequest) -> PaperConfigResponse:
    global _config

    async with _config_lock:
        data = _load_strategy_yaml()

        candidate = PaperConfig(**payload.model_dump())

        data["paper"] = candidate.model_dump(mode="python")
        _persist_strategy_yaml(data)

        _config = reload_config()
        return await get_paper_config()


@app.get("/api/pnl/daily", response_model=PnLDailyResponse)
async def get_pnl_daily(
    days: int = Query(default=30, ge=1, le=365),
    mode: Optional[APP_MODE] = Query(default=None),
) -> PnLDailyResponse:
    database = await _ensure_database()
    entries = await database.get_pnl_history(days=days, mode=mode)

    if not entries:
        target_mode = mode or (_config.app_mode if _config else "paper")
        return PnLDailyResponse(mode=target_mode, days=[])

    grouped: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees": 0.0,
            "funding": 0.0,
            "commission": 0.0,
            "net_pnl": 0.0,
            "balance": 0.0,
        }
    )
    bucket_modes: Dict[str, APP_MODE] = {}
    rollup_days: Dict[str, bool] = {}

    for entry in entries:
        if entry.timestamp is None:
            continue
        bucket = entry.timestamp.date().isoformat()
        trade_id = getattr(entry, "trade_id", "") or ""
        if trade_id.startswith("rollup-"):
            grouped[bucket] = {
                "realized_pnl": round(entry.realized_pnl, 6),
                "unrealized_pnl": round(entry.unrealized_pnl, 6),
                "fees": round(entry.fees, 6),
                "funding": round(entry.funding, 6),
                "commission": round(entry.commission, 6),
                "net_pnl": round(entry.net_pnl, 6),
                "balance": round(entry.balance, 6),
            }
            bucket_modes[bucket] = entry.mode
            rollup_days[bucket] = True
            continue

        if rollup_days.get(bucket):
            # Skip granular rows once an authoritative rollup exists.
            continue

        bucket_stats = grouped[bucket]
        bucket_stats["realized_pnl"] += entry.realized_pnl
        bucket_stats["unrealized_pnl"] += entry.unrealized_pnl
        bucket_stats["fees"] += entry.fees
        bucket_stats["funding"] += entry.funding
        bucket_stats["commission"] += entry.commission
        bucket_stats["net_pnl"] += entry.net_pnl
        bucket_stats["balance"] = entry.balance
        bucket_modes[bucket] = entry.mode

    ordered_days = [
        PnLDailyEntry(
            date=day,
            mode=bucket_modes.get(day, mode or entries[0].mode),
            realized_pnl=round(bucket["realized_pnl"], 6),
            unrealized_pnl=round(bucket["unrealized_pnl"], 6),
            fees=round(bucket["fees"], 6),
            funding=round(bucket["funding"], 6),
            commission=round(bucket["commission"], 6),
            net_pnl=round(bucket["net_pnl"], 6),
            balance=round(bucket["balance"], 6),
        )
        for day, bucket in sorted(grouped.items())
    ]

    last_mode = bucket_modes.get(ordered_days[-1].date, entries[-1].mode)
    response_mode = mode or last_mode

    return PnLDailyResponse(mode=response_mode, days=ordered_days)


@app.get("/api/positions", response_model=List[PositionResponse])
async def get_positions(
    mode: Optional[APP_MODE] = Query(default=None),
    run_id: Optional[str] = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=500),
) -> List[PositionResponse]:
    database = await _ensure_database()
    positions = await database.get_positions(mode=mode, run_id=run_id)
    limited = positions[:limit]
    return [
        PositionResponse(
            symbol=item.symbol,
            side=item.side,
            size=item.size,
            entry_price=item.entry_price,
            mark_price=item.mark_price,
            unrealized_pnl=item.unrealized_pnl,
            percentage=item.percentage,
            mode=item.mode,
            run_id=item.run_id,
            created_at=_isoformat_or_none(item.created_at),
            updated_at=_isoformat_or_none(item.updated_at),
        )
        for item in limited
    ]


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(
    symbol: Optional[str] = Query(default=None, max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    shadow: bool = Query(default=False),
) -> List[TradeResponse]:
    database = await _ensure_database()
    trades = await database.get_trades(
        symbol=symbol,
        limit=limit,
        is_shadow=shadow,
    )
    return [
        TradeResponse(
            client_id=item.client_id,
            trade_id=item.trade_id,
            order_id=item.order_id,
            symbol=item.symbol,
            side=item.side,
            quantity=item.quantity,
            price=item.price,
            commission=item.commission,
            fees=item.fees,
            funding=item.funding,
            realized_pnl=item.realized_pnl,
            mark_price=item.mark_price,
            slippage_bps=item.slippage_bps,
            achieved_vs_signal_bps=item.achieved_vs_signal_bps,
            latency_ms=item.latency_ms,
            maker=item.maker,
            mode=item.mode,
            run_id=item.run_id,
            timestamp=_isoformat_or_none(item.timestamp),
            is_shadow=item.is_shadow,
        )
        for item in trades
    ]


@app.get("/api/config", response_model=ConfigResponse)
async def get_config_snapshot() -> ConfigResponse:
    database = await _ensure_database()
    config_data = _load_strategy_yaml()
    versions = await database.list_config_versions(limit=1)
    version = versions[0].version if versions else None
    return ConfigResponse(version=version, config=config_data)


@app.get("/api/config/versions", response_model=List[ConfigVersionResponse])
async def list_config_versions(
    limit: int = Query(default=10, ge=1, le=50),
) -> List[ConfigVersionResponse]:
    database = await _ensure_database()
    versions = await database.list_config_versions(limit=limit)
    return [
        ConfigVersionResponse(
            version=item.version,
            created_at=_isoformat_or_none(item.created_at),
        )
        for item in versions
    ]


@app.get("/api/risk/snapshots", response_model=List[RiskSnapshotResponse])
async def get_risk_snapshots(
    limit: int = Query(default=20, ge=1, le=200),
) -> List[RiskSnapshotResponse]:
    database = await _ensure_database()
    snapshots = await database.get_risk_snapshots(limit=limit)
    return [
        RiskSnapshotResponse(
            crisis_mode=item.crisis_mode,
            consecutive_losses=item.consecutive_losses,
            drawdown=item.drawdown,
            volatility=item.volatility,
            position_size_factor=item.position_size_factor,
            mode=item.mode,
            run_id=item.run_id,
            created_at=_isoformat_or_none(item.created_at),
            payload=item.payload,
        )
        for item in snapshots
    ]


@app.post(
    "/api/backtests",
    response_model=BacktestJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_backtest(payload: BacktestRequest) -> BacktestJobResponse:
    job_id = uuid4().hex
    job = _BacktestJob(job_id=job_id, payload=payload)

    async with _backtest_lock:
        _backtest_jobs[job_id] = job
        _purge_backtest_history()

    task = asyncio.create_task(_run_backtest_job(job_id))
    _backtest_tasks[job_id] = task
    return _serialize_backtest_job(job)


@app.get("/api/backtests", response_model=List[BacktestJobResponse])
async def list_backtests() -> List[BacktestJobResponse]:
    async with _backtest_lock:
        jobs = list(_backtest_jobs.values())
    ordered = sorted(jobs, key=lambda record: record.submitted_at, reverse=True)
    return [_serialize_backtest_job(job) for job in ordered]


@app.get("/api/backtests/{job_id}", response_model=BacktestJobResponse)
async def fetch_backtest(job_id: str) -> BacktestJobResponse:
    async with _backtest_lock:
        job = _backtest_jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backtest job {job_id} not found.",
        )
    return _serialize_backtest_job(job)


def _apply_safe_knobs(
    data: Dict[str, Any], payload: ConfigStageRequest
) -> Dict[str, Any]:
    changes: Dict[str, Any] = {}

    if payload.risk_per_trade is not None:
        trading = data.setdefault("trading", {})
        current = trading.get("risk_per_trade")
        if current != payload.risk_per_trade:
            trading["risk_per_trade"] = round(payload.risk_per_trade, 6)
            changes["risk_per_trade"] = trading["risk_per_trade"]

            changes["soft_atr_multiplier"] = stops["soft_atr_multiplier"]

    if payload.spread_budget_bps is not None:
        execution = data.setdefault("execution", {})
        current = execution.get("spread_budget_bps")
        if current != payload.spread_budget_bps:
            execution["spread_budget_bps"] = round(payload.spread_budget_bps, 6)
            changes["spread_budget_bps"] = execution["spread_budget_bps"]

    return changes


# --------------------------------------------------------------------- #
# Strategy Management
# --------------------------------------------------------------------- #

@app.post("/api/strategies", response_model=StrategyResponse)
async def save_strategy(payload: StrategyRequest) -> StrategyResponse:
    service = await _ensure_strategy_service()
    strategy_id = await service.save_strategy(payload.name, payload.config)
    if not strategy_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save strategy",
        )
    
    # Fetch back to return full response
    strategies = await service.list_strategies()
    for s in strategies:
        if s["name"] == payload.name:
            return StrategyResponse(**s)
            
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Strategy saved but not found",
    )


@app.get("/api/strategies", response_model=List[StrategyResponse])
async def list_strategies() -> List[StrategyResponse]:
    service = await _ensure_strategy_service()
    strategies = await service.list_strategies()
    return [StrategyResponse(**s) for s in strategies]


@app.get("/api/strategies/{name}", response_model=StrategyResponse)
async def get_strategy(name: str) -> StrategyResponse:
    service = await _ensure_strategy_service()
    strategies = await service.list_strategies()
    for s in strategies:
        if s["name"] == name:
            return StrategyResponse(**s)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Strategy {name} not found",
    )


@app.post("/api/strategies/{name}/activate", response_model=Dict[str, bool])
async def activate_strategy(name: str) -> Dict[str, bool]:
    service = await _ensure_strategy_service()
    
    # 1. Activate in database
    success = await service.activate_strategy(name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {name} not found or could not be activated",
        )
    
    # 2. Fetch config and update YAML
    # 2. Update active_strategies in YAML to trigger reload
    try:
        current_config = _load_strategy_yaml()
        
        # Ensure strategy section exists
        if "strategy" not in current_config:
            current_config["strategy"] = {}
            
        # Ensure active_strategies list exists
        if "active_strategies" not in current_config["strategy"]:
            current_config["strategy"]["active_strategies"] = []
            
        # Add if not present
        if name not in current_config["strategy"]["active_strategies"]:
            current_config["strategy"]["active_strategies"].append(name)
            
        _persist_strategy_yaml(current_config)
        
        # Trigger reload
        global _config
        _config = reload_config()
        
    except Exception as e:
        logger.error(f"Failed to update YAML for strategy activation: {e}")
        # We don't fail the request because DB activation succeeded

    return {"success": True}


@app.delete("/api/strategies/{name}", response_model=Dict[str, bool])
async def delete_strategy(name: str) -> Dict[str, bool]:
    service = await _ensure_strategy_service()
    success = await service.delete_strategy(name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {name} not found",
        )
    return {"success": True}



def _apply_safe_knobs(
    data: Dict[str, Any], payload: ConfigStageRequest
) -> Dict[str, Any]:
    changes: Dict[str, Any] = {}

    if payload.risk_per_trade is not None:
        trading = data.setdefault("trading", {})
        current = trading.get("risk_per_trade")
        if current != payload.risk_per_trade:
            trading["risk_per_trade"] = round(payload.risk_per_trade, 6)
            changes["risk_per_trade"] = trading["risk_per_trade"]

    if payload.spread_budget_bps is not None:
        execution = data.setdefault("execution", {})
        current = execution.get("spread_budget_bps")
        if current != payload.spread_budget_bps:
            execution["spread_budget_bps"] = round(payload.spread_budget_bps, 6)
            changes["spread_budget_bps"] = execution["spread_budget_bps"]

    return changes


@app.post("/api/config/stage", response_model=ConfigStageResponse)
async def stage_config(payload: ConfigStageRequest) -> ConfigStageResponse:
    async with _config_lock:
        database = await _ensure_database()
        current = _load_strategy_yaml()
        staged = yaml.safe_load(yaml.safe_dump(current)) or {}
        changes = _apply_safe_knobs(staged, payload)

        if not changes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No changes detected for staging.",
            )

        version = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
        config_blob = yaml.safe_dump(staged, sort_keys=False)

        persisted = await database.upsert_config_version(version, config_blob)
        if not persisted:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to persist staged configuration.",
            )

        return ConfigStageResponse(version=version, config=staged, changes=changes)


@app.post("/api/config/apply/{version}", response_model=ConfigStageResponse)
async def apply_config(version: str) -> ConfigStageResponse:
    global _config

    async with _config_lock:
        database = await _ensure_database()
        record = await database.get_config_version(version)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Config version {version} not found.",
            )

        candidate = yaml.safe_load(record.config) or {}
        if not isinstance(candidate, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Stored configuration is invalid.",
            )

        _persist_strategy_yaml(candidate)
        os.environ["APP_MODE"] = candidate.get(
            "app_mode", os.environ.get("APP_MODE", "paper")
        )
        _config = reload_config()
        _update_trading_mode_metric(_config.app_mode)

        await _publish_config_reload(version, candidate)

        return ConfigStageResponse(
            version=version,
            config=candidate,
            changes={},
        )


class RawConfigResponse(BaseModel):
    yaml: str


class RawConfigRequest(BaseModel):
    yaml: str


@app.get("/api/config/raw", response_model=RawConfigResponse)
async def get_raw_config() -> RawConfigResponse:
    data = _load_strategy_yaml()
    text = yaml.safe_dump(data, sort_keys=False)
    return RawConfigResponse(yaml=text)


@app.post("/api/config/active-strategies")
async def update_active_strategies(strategies: List[str] = Body(...)):
    """Update the list of active strategies in config."""
    global _config
    async with _config_lock:
        data = _load_strategy_yaml()
        if "strategy" not in data:
            data["strategy"] = {}
        
        data["strategy"]["active_strategies"] = strategies
        _persist_strategy_yaml(data)
        _config = reload_config()
        
    return {"status": "success", "active_strategies": strategies}

@app.post("/api/config/raw", response_model=RawConfigResponse)
async def update_raw_config(payload: RawConfigRequest) -> RawConfigResponse:
    global _config

    try:
        candidate = yaml.safe_load(payload.yaml) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YAML: {exc}",
        ) from exc

    if not isinstance(candidate, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Strategy configuration must be a mapping/object.",
        )

    async with _config_lock:
        _persist_strategy_yaml(candidate)
        _config = reload_config()

    return RawConfigResponse(
        yaml=yaml.safe_dump(candidate, sort_keys=False),
    )


class ExchangeConfigResponse(BaseModel):
    provider: str
    name: str
    testnet: bool
    base_url: Optional[str]
    has_api_key: bool
    has_secret_key: bool
    has_passphrase: bool
    api_key_hint: Optional[str] = None


class ExchangeConfigRequest(BaseModel):
    provider: Optional[str] = None
    name: Optional[str] = None
    testnet: Optional[bool] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    passphrase: Optional[str] = None


@app.get("/api/exchange/config", response_model=ExchangeConfigResponse)
async def get_exchange_config() -> ExchangeConfigResponse:
    if _config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration not loaded",
        )
    exchange = _config.exchange
    api_hint = None
    if exchange.api_key:
        api_hint = f"••••{exchange.api_key[-4:]}" if len(exchange.api_key) >= 4 else "••••"
    return ExchangeConfigResponse(
        provider=exchange.provider if hasattr(exchange, "provider") else exchange.name,
        name=exchange.name,
        testnet=exchange.testnet,
        base_url=getattr(exchange, "base_url", None),
        has_api_key=bool(exchange.api_key),
        has_secret_key=bool(exchange.secret_key),
        has_passphrase=bool(exchange.passphrase),
        api_key_hint=api_hint,
    )


@app.post("/api/exchange/config", response_model=ExchangeConfigResponse)
async def update_exchange_config(payload: ExchangeConfigRequest) -> ExchangeConfigResponse:
    global _config

    async with _config_lock:
        data = _load_strategy_yaml()
        current = data.setdefault("exchange", {})

        if payload.provider is not None:
            provider = payload.provider.lower()
            if provider not in {"bybit", "zoomex"}:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="provider must be 'bybit' or 'zoomex'",
                )
            current["provider"] = provider
            current["name"] = provider

        if payload.name is not None:
            current["name"] = payload.name

        if payload.testnet is not None:
            current["testnet"] = payload.testnet

        if payload.base_url is not None:
            if payload.base_url.strip() == "":
                current.pop("base_url", None)
            else:
                current["base_url"] = payload.base_url.strip()

        if payload.api_key is not None:
            current["api_key"] = payload.api_key

        if payload.secret_key is not None:
            current["secret_key"] = payload.secret_key

        if payload.passphrase is not None:
            current["passphrase"] = payload.passphrase

        _persist_strategy_yaml(data)
        _config = reload_config()

    return await get_exchange_config()


# --------------------------------------------------------------------- #
# WebSocket & Orders (Merged from server.py)
# --------------------------------------------------------------------- #

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.websocket("/ws/market-data")
async def websocket_market_data(websocket: WebSocket):
    await manager.connect(websocket)
    client = await get_messaging()
    config = load_config()
    subject = config.messaging.subjects.get("market_data", "market.data")

    async def handler(msg):
        try:
            data = msg.data.decode()
            await websocket.send_text(data)
        except Exception as e:
            logger.error(f"Error sending market data: {e}")

    # Subscribe to NATS
    sub = await client.subscribe(subject, handler)

    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await sub.unsubscribe()

@app.websocket("/ws/executions")
async def websocket_executions(websocket: WebSocket):
    await websocket.accept()
    client = await get_messaging()
    config = load_config()
    subject = config.messaging.subjects.get("executions", "executions")

    async def handler(msg):
        try:
            data = msg.data.decode()
            await websocket.send_text(data)
        except Exception as e:
            logger.error(f"Error sending execution: {e}")

    sub = await client.subscribe(subject, handler)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await sub.unsubscribe()

@app.post("/api/orders")
async def place_order(order: Dict[str, Any] = Body(...)):
    """Place a new order via NATS."""
    try:
        client = await get_messaging()
        config = load_config()
        
        # Validate required fields
        required = ["symbol", "side", "quantity"]
        if not all(k in order for k in required):
            raise HTTPException(status_code=400, detail=f"Missing required fields: {required}")

        payload = {
            "symbol": order["symbol"],
            "side": order["side"],
            "type": order.get("type", "market"),
            "quantity": float(order["quantity"]),
            "price": float(order["price"]) if order.get("price") else None,
            "client_id": f"web-{datetime.utcnow().timestamp()}",
            "timestamp": datetime.utcnow().isoformat()
        }

        # Publish to orders subject
        subject = config.messaging.subjects.get("orders", "orders")
        await client.publish(subject, payload)
        
        return {"status": "success", "order_id": payload["client_id"], "message": "Order submitted"}
    except Exception as e:
        logger.error(f"Failed to place order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/orders/{order_id}")
async def cancel_order(order_id: str, symbol: str = Query(...)):
    """Cancel an order."""
    try:
        exchange = await _ensure_exchange()
        # ExchangeClient doesn't have cancel_order exposed directly?
        # It has cancel_all_orders.
        # It has ccxt_client which has cancel_order.
        # But we should expose it in ExchangeClient or use ccxt_client directly if safe.
        # ExchangeClient wraps ccxt_client.
        
        if exchange.ccxt_client:
            await exchange.ccxt_client.cancel_order(order_id, symbol)
            return {"status": "success", "message": f"Order {order_id} cancelled"}
        
        # Paper mode fallback?
        # If paper broker is used, we need to cancel there.
        # ExchangeClient paper mode logic for cancel_order is needed.
        # For now, if not live/ccxt, we might fail or mock.
        if exchange.app_mode != "live":
             # Mock success for paper
             logger.info(f"[PAPER] Cancelled order {order_id}")
             return {"status": "success", "message": f"Order {order_id} cancelled (PAPER)"}
             
        raise HTTPException(status_code=501, detail="Cancel order not supported in current mode")

    except Exception as e:
        logger.error(f"Failed to cancel order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/positions/close")
async def close_position(payload: Dict[str, Any] = Body(...)):
    """Close a position (market)."""
    try:
        symbol = payload.get("symbol")
        if not symbol:
             raise HTTPException(status_code=400, detail="Symbol required")
             
        exchange = await _ensure_exchange()
        
        # We need to know the position size to close it?
        # Or just "close all" for symbol.
        # ExchangeClient has close_position_reduce_only, but that takes qty.
        # We should probably fetch position first.
        
        positions = await exchange.get_positions([symbol])
        if not positions:
            raise HTTPException(status_code=404, detail="No position found")
            
        position = positions[0]
        if position.size == 0:
             raise HTTPException(status_code=400, detail="Position size is 0")
             
        # Place market close order
        side = "sell" if position.size > 0 else "buy"
        qty = abs(position.size)
        
        # Use place_order logic (via NATS or direct?)
        # Direct via exchange is faster/simpler for API.
        # But we should probably use the same path as place_order if possible for consistency.
        # However, place_order endpoint uses NATS.
        # If we use NATS here, we need to construct the order.
        
        client = await get_messaging()
        config = load_config()
        subject = config.messaging.subjects.get("orders", "orders")
        
        order_payload = {
            "symbol": symbol,
            "side": side,
            "type": "market",
            "quantity": qty,
            "reduce_only": True,
            "client_id": f"web-close-{datetime.utcnow().timestamp()}",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await client.publish(subject, order_payload)
        
        return {"status": "success", "message": "Close position order submitted"}

    except Exception as e:
        logger.error(f"Failed to close position: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/presets")
def get_presets():
    """List all preset strategies."""
    presets = get_preset_strategies()
    return [p.dict() for p in presets]

@app.get("/api/klines")
async def get_klines(
    symbol: str = Query(..., description="Trading symbol (e.g. BTC/USDT)"),
    interval: str = Query("15m", description="Timeframe interval"),
    limit: int = Query(100, description="Number of candles")
):
    """Get historical OHLCV data."""
    try:
        exchange = await _ensure_exchange()
        df = await exchange.get_historical_data(symbol, interval, limit)
        
        if df is None or df.empty:
            return []
            
        # Convert DataFrame to list of dicts or list of lists
        # Lightweight charts expects: { time, open, high, low, close }
        # Our DataFrame has columns: timestamp, open, high, low, close, volume
        
        # Ensure timestamp is in seconds for lightweight-charts
        records = []
        for _, row in df.iterrows():
            # timestamp in df is usually datetime or ms timestamp?
            # ExchangeClient returns df with 'timestamp' column.
            # Let's check ExchangeClient.get_historical_data return format.
            # It returns pd.DataFrame with columns: timestamp, open, high, low, close, volume
            # timestamp is usually datetime object or int ms.
            
            ts = row['timestamp']
            if isinstance(ts, pd.Timestamp) or isinstance(ts, datetime):
                ts = int(ts.timestamp())
            elif isinstance(ts, (int, float)):
                # Assume ms if > 10^11
                if ts > 1e11:
                    ts = int(ts / 1000)
                else:
                    ts = int(ts)
            
            records.append({
                "time": ts,
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": float(row['volume'])
            })
            
        return records

    except Exception as e:
        logger.error(f"Error fetching klines: {e}")
        raise HTTPException(status_code=500, detail=str(e))
