from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends, status

from src.api.models import StrategyResponse, StrategyRequest
from src.database import DatabaseManager, Strategy

strategy_router = APIRouter()

# Dependency placeholder - will be overridden by main.py
async def get_db() -> DatabaseManager:
    raise NotImplementedError


@strategy_router.get("/api/strategies", response_model=List[StrategyResponse])
async def list_strategies(db: DatabaseManager = Depends(get_db)):
    """List all available strategies."""
    strategies = await db.get_strategies()
    return strategies


@strategy_router.post("/api/strategies", response_model=StrategyResponse)
async def create_strategy(request: StrategyRequest, db: DatabaseManager = Depends(get_db)):
    """Create a new strategy configuration."""
    # Convert API model to DB model
    # Note: StrategyRequest doesn't have is_active, defaulting to False
    db_strategy = Strategy(
        name=request.name,
        config=request.config,
        is_active=False
    )
    
    strategy_id = await db.create_strategy(db_strategy)
    if not strategy_id:
        raise HTTPException(status_code=500, detail="Failed to create strategy")
    
    # Fetch back to return full object with ID and timestamps
    created = await db.get_strategy(strategy_id)
    if not created:
        raise HTTPException(status_code=404, detail="Strategy created but not found")
    
    # Convert datetime fields to strings for response
    return StrategyResponse(
        id=created.id,
        name=created.name,
        config=created.config,
        is_active=created.is_active,
        created_at=created.created_at.isoformat() if created.created_at else None,
        updated_at=created.updated_at.isoformat() if created.updated_at else None,
    )


@strategy_router.get("/api/strategies/{strategy_name}", response_model=StrategyResponse)
async def get_strategy_by_name(strategy_name: str, db: DatabaseManager = Depends(get_db)):
    """Get a specific strategy by name or ID."""
    # Try to parse as ID first
    try:
        strategy_id = int(strategy_name)
        strategy = await db.get_strategy(strategy_id)
    except ValueError:
        # It's a name, search by name
        strategy = await db.get_strategy_by_name(strategy_name)
    
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    return StrategyResponse(
        id=strategy.id,
        name=strategy.name,
        config=strategy.config,
        is_active=strategy.is_active,
        created_at=strategy.created_at.isoformat() if strategy.created_at else None,
        updated_at=strategy.updated_at.isoformat() if strategy.updated_at else None,
    )


@strategy_router.put("/api/strategies/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(strategy_id: int, request: StrategyRequest, db: DatabaseManager = Depends(get_db)):
    """Update an existing strategy."""
    existing = await db.get_strategy(strategy_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Update fields
    existing.name = request.name
    existing.config = request.config
    
    success = await db.update_strategy(existing)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update strategy")
        
    # Fetch updated
    updated = await db.get_strategy(strategy_id)
    return updated


@strategy_router.post("/api/strategies/{strategy_id}/activate", response_model=StrategyResponse)
async def activate_strategy(strategy_id: int, db: DatabaseManager = Depends(get_db)):
    """Activate a strategy and deactivate others (if single active strategy logic applies)."""
    # For now, we allow toggling, but usually we might want only one active.
    # Let's implementation simple toggle to Active=True. 
    # If we want mutually exclusive active strategies, we should handle that in business logic here.
    # Let's enforce single active strategy for now to be safe.
    
    # 1. Deactivate all others? Or just set this one true.
    # The requirement didn't specify, but typical bot has 1 active strategy.
    # However, let's just enable this one.
    
    success = await db.toggle_strategy_active(strategy_id, True)
    if not success:
        raise HTTPException(status_code=404, detail="Strategy not found or update failed")

    return await db.get_strategy(strategy_id)


@strategy_router.post("/api/strategies/{strategy_id}/deactivate", response_model=StrategyResponse)
async def deactivate_strategy(strategy_id: int, db: DatabaseManager = Depends(get_db)):
    """Deactivate a strategy."""
    success = await db.toggle_strategy_active(strategy_id, False)
    if not success:
        raise HTTPException(status_code=404, detail="Strategy not found or update failed")

    return await db.get_strategy(strategy_id)

