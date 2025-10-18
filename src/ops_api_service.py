"""
FastAPI-based ops API service for mode management and paper configuration.

The service replaces the Go implementation to simplify configuration updates
and provide richer introspection without requiring a Go toolchain locally.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
from uuid import uuid4

import yaml
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import (
    APP_MODE,
    PaperConfig,
    TradingBotConfig,
    get_config,
    reload_config,
)
from .database import DatabaseManager
from .messaging import MessagingClient
from .metrics import TRADING_MODE

MODES: List[APP_MODE] = ["live", "paper", "replay"]

logger = logging.getLogger(__name__)


class ModeRequest(BaseModel):
    mode: APP_MODE
    shadow: bool = Field(default=False, description="Enable shadow paper fills")


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
    mode: APP_MODE
    realized_pnl: float
    unrealized_pnl: float
    fees: float
    funding: float
    commission: float
    net_pnl: float
    balance: float


class PnLDailyResponse(BaseModel):
    mode: APP_MODE
    days: List[PnLDailyEntry]


class PositionResponse(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    percentage: float
    mode: APP_MODE
    run_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TradeResponse(BaseModel):
    client_id: str
    trade_id: str
    order_id: str
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
    mode: APP_MODE
    run_id: str
    timestamp: Optional[str] = None
    is_shadow: bool = False


class RiskSnapshotResponse(BaseModel):
    crisis_mode: bool
    consecutive_losses: int
    drawdown: float
    volatility: float
    position_size_factor: float
    mode: APP_MODE
    run_id: str
    created_at: Optional[str] = None
    payload: Dict[str, Any]


class BacktestRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", min_length=3, max_length=40)
    start: date = Field(
        default_factory=lambda: date.today().replace(day=1),
        description="Start date (YYYY-MM-DD)",
    )
    end: date = Field(
        default_factory=date.today, description="End date (YYYY-MM-DD)"
    )

    @model_validator(mode="after")
    def _validate_range(self) -> "BacktestRequest":
        if self.start > self.end:
            raise ValueError("Start date must be on or before end date.")
        return self


class BacktestJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    symbol: str
    start: str
    end: str
    submitted_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    result: Optional[Dict[str, Any]]
    error: Optional[str]


@dataclass
class _BacktestJob:
    job_id: str
    payload: BacktestRequest
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    submitted_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ConfigVersionResponse(BaseModel):
    version: str
    created_at: Optional[str] = None


class ConfigResponse(BaseModel):
    version: Optional[str]
    config: Dict[str, Any]


class ConfigStageRequest(BaseModel):
    risk_per_trade: Optional[float] = Field(default=None, ge=0.001, le=0.05)
    soft_atr_multiplier: Optional[float] = Field(default=None, ge=0.1, le=5.0)
    spread_budget_bps: Optional[float] = Field(default=None, ge=1, le=50)

    @model_validator(mode="after")
    def _ensure_payload(self) -> "ConfigStageRequest":
        if (
            self.risk_per_trade is None
            and self.soft_atr_multiplier is None
            and self.spread_budget_bps is None
        ):
            raise ValueError("At least one knob must be provided.")
        return self


class ConfigStageResponse(BaseModel):
    version: str
    config: Dict[str, Any]
    changes: Dict[str, Any]


app = FastAPI(title="Trading Ops API", version="2.0.0")

_config_lock = asyncio.Lock()
_config: Optional[TradingBotConfig] = None
_database: Optional[DatabaseManager] = None
_messaging: Optional[MessagingClient] = None
_rollup_task: Optional[asyncio.Task[None]] = None
_backtest_lock = asyncio.Lock()
_backtest_jobs: Dict[str, _BacktestJob] = {}
_BACKTEST_HISTORY_LIMIT = 8
_backtest_tasks: Dict[str, asyncio.Task[None]] = {}


async def _ensure_database() -> DatabaseManager:
    if _database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialised",
        )
    return _database


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
        start=job.payload.start.isoformat(),
        end=job.payload.end.isoformat(),
        submitted_at=_isoformat(job.submitted_at),
        started_at=_isoformat_or_none(job.started_at),
        completed_at=_isoformat_or_none(job.completed_at),
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
            job.payload.start.isoformat(),
            job.payload.end.isoformat(),
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


@app.on_event("startup")
async def startup() -> None:
    global _config, _database, _messaging, _rollup_task

    _config = get_config()
    _update_trading_mode_metric(_config.app_mode)

    _database = DatabaseManager(_config.database.path)
    await _database.initialize()

    messaging_config = {"servers": _config.messaging.servers}
    _messaging = MessagingClient(messaging_config)
    try:
        await _messaging.connect()
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.warning("Unable to connect to NATS for config reloads: %s", exc)
        _messaging = None

    try:
        initial_rollup = await _database.aggregate_daily_pnl(days=60)
        for entry in initial_rollup:
            await _database.add_pnl_entry(entry)
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.warning("Initial PnL rollup failed: %s", exc)

    _rollup_task = asyncio.create_task(_pnl_rollup_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    global _database, _messaging, _rollup_task

    if _rollup_task:
        _rollup_task.cancel()
        try:
            await _rollup_task
        except asyncio.CancelledError:
            pass
        _rollup_task = None

    async with _backtest_lock:
        tasks = list(_backtest_tasks.values())
        _backtest_tasks.clear()

    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    if _messaging:
        await _messaging.close()
    _messaging = None

    if _database:
        await _database.close()
    _database = None


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

    if payload.soft_atr_multiplier is not None:
        risk = data.setdefault("risk_management", {})
        stops = risk.setdefault("stops", {})
        current = stops.get("soft_atr_multiplier")
        if current != payload.soft_atr_multiplier:
            stops["soft_atr_multiplier"] = round(payload.soft_atr_multiplier, 6)
            changes["soft_atr_multiplier"] = stops["soft_atr_multiplier"]

    if payload.spread_budget_bps is not None:
        paper = data.setdefault("paper", {})
        current = paper.get("max_slippage_bps")
        if current != payload.spread_budget_bps:
            paper["max_slippage_bps"] = round(payload.spread_budget_bps, 4)
            changes["max_slippage_bps"] = paper["max_slippage_bps"]

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
