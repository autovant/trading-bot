"""
FastAPI-based ops API service for mode management and paper configuration.

The service replaces the Go implementation to simplify configuration updates
and provide richer introspection without requiring a Go toolchain locally.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from .config import (
    APP_MODE,
    PaperConfig,
    TradingBotConfig,
    get_config,
    reload_config,
)
from .database import DatabaseManager

MODES: List[APP_MODE] = ["live", "paper", "replay"]


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


app = FastAPI(title="Trading Ops API", version="2.0.0")

_config_lock = asyncio.Lock()
_config: Optional[TradingBotConfig] = None
_database: Optional[DatabaseManager] = None

_trading_mode_metric = Gauge(
    "trading_mode",
    "Current trading mode",
    ["mode"],
)


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
        _trading_mode_metric.labels(mode=candidate).set(1 if candidate == mode else 0)


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


@app.on_event("startup")
async def startup() -> None:
    global _config, _database

    _config = get_config()
    _update_trading_mode_metric(_config.app_mode)

    _database = DatabaseManager(_config.database.path)
    await _database.initialize()


@app.on_event("shutdown")
async def shutdown() -> None:
    global _database
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

    for entry in entries:
        if entry.timestamp is None:
            continue
        bucket = entry.timestamp.date().isoformat()
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
