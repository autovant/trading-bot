import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, cast

from fastapi import APIRouter, HTTPException, Depends, Security, status
from fastapi.security import APIKeyHeader
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, REGISTRY, Gauge
from fastapi.responses import Response
import yaml
from pathlib import Path

from src.config import (
    APP_MODE,
    TradingBotConfig,
    load_config,
    reload_config,
    get_config,
)
from src.api.models import (
    ModeResponse,
    ModeRequest,
    BotStatusResponse,
)
# We need logging
import logging
logger = logging.getLogger(__name__)

system_router = APIRouter()

# --- Dependencies & Global State Access ---
API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key_header: str = Security(api_key_header)):
    import os
    expected_key = os.getenv("API_KEY", "default-insecure-key")
    if api_key_header == expected_key:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Could not validate credentials",
    )

if "trading_mode" in REGISTRY._names_to_collectors:
    TRADING_MODE = REGISTRY._names_to_collectors["trading_mode"]
else:
    TRADING_MODE = Gauge(
        "trading_mode",
        "Current application mode (1=active, 0=inactive)",
        ["service", "mode"],
    )

# Globals helpers
_config_lock = asyncio.Lock()

def _strategy_config_path() -> Path:
    config = get_config()
    return Path(config.config_paths.strategy)

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

async def _publish_config_reload(version: str, config_body: Dict[str, Any], messaging: Any) -> None:
    if not messaging:
        return
    
    subject = "config.reload" # simplified for refactor
    payload = {
        "version": version,
        "mode": "live", # Placeholder
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await messaging.publish(subject, payload)
    except Exception as exc:
        logger.error("Failed to publish config.reload: %s", exc)

# Helper to get messaging dependency
def get_messaging():
    # Will be overridden
    return None

@system_router.get("/api/health", response_model=Dict[str, str])
async def health() -> Dict[str, str]:
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@system_router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@system_router.get("/api/mode", response_model=ModeResponse)
async def get_mode() -> ModeResponse:
    config = get_config()
    return ModeResponse(mode=config.app_mode, shadow=config.shadow_paper)


@system_router.get("/api/bot/status", response_model=BotStatusResponse)
async def get_bot_status() -> BotStatusResponse:
    config = get_config()
    # Safely check perps config
    enabled = False
    symbol = "BTC-PERP"
    if hasattr(config, "perps"):
        enabled = config.perps.enabled
        symbol = config.perps.symbol
    
    status_str = "running" if enabled else "stopped"
    return BotStatusResponse(
        enabled=enabled,
        status=status_str,
        symbol=symbol,
        mode=config.app_mode,
    )

@system_router.post("/api/bot/start", dependencies=[Depends(get_api_key)])
async def start_bot(messaging: Any = Depends(get_messaging)) -> BotStatusResponse:
    async with _config_lock:
        data = _load_strategy_yaml()
        if "perps" not in data:
            data["perps"] = {}
        data["perps"]["enabled"] = True
        _persist_strategy_yaml(data)
        reload_config()

        await _publish_config_reload(version="manual_start", config_body={}, messaging=messaging)

    return await get_bot_status()

@system_router.post("/api/bot/stop", dependencies=[Depends(get_api_key)])
async def stop_bot(messaging: Any = Depends(get_messaging)) -> BotStatusResponse:
    async with _config_lock:
        data = _load_strategy_yaml()
        if "perps" not in data:
            data["perps"] = {}
        data["perps"]["enabled"] = False
        _persist_strategy_yaml(data)
        reload_config()

        await _publish_config_reload(version="manual_stop", config_body={}, messaging=messaging)

    return await get_bot_status()
