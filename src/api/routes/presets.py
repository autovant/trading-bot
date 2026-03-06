import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)

presets_router = APIRouter(tags=["presets"])


class PresetBacktestRequest(BaseModel):
    symbol: str = Field(..., description="Trading pair, e.g. BTCUSDT")
    timeframe: str = Field(default="1h", description="Candle timeframe")
    start_date: str = Field(..., description="Backtest start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Backtest end date (YYYY-MM-DD)")
    params: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional parameter overrides for the strategy"
    )


@presets_router.get("/api/strategies/presets")
async def list_presets():
    """List all available strategy presets with metadata."""
    presets = StrategyRegistry.list_presets()
    return {"presets": presets, "total": len(presets)}


@presets_router.get("/api/strategies/presets/{preset_key}")
async def get_preset(preset_key: str):
    """Get a specific preset's full metadata + default params."""
    preset = StrategyRegistry.get_preset(preset_key)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_key}' not found")
    return preset


@presets_router.post("/api/strategies/presets/{preset_key}/backtest")
async def backtest_preset(preset_key: str, request: PresetBacktestRequest):
    """Run a backtest with a preset strategy."""
    preset = StrategyRegistry.get_preset(preset_key)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_key}' not found")

    try:
        _strategy = StrategyRegistry.instantiate(
            preset_key, request.symbol, request.params
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail="Failed to instantiate strategy",
        ) from e

    # Return the configuration that would be used for a backtest
    # Actual backtest execution should go through the existing backtest endpoint
    merged_params = {**preset.get("default_params", {})}
    if request.params:
        merged_params.update(request.params)

    return {
        "preset_key": preset_key,
        "strategy_name": preset["name"],
        "symbol": request.symbol,
        "timeframe": request.timeframe,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "params": merged_params,
        "status": "ready",
        "message": "Strategy validated. Submit to /api/backtests to execute.",
    }
