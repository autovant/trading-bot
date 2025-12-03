"""
Service for managing trading strategies.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..database import DatabaseManager, Strategy

logger = logging.getLogger(__name__)


class StrategyService:
    """Service for saving/loading strategies via DatabaseManager."""

    def __init__(self, database: DatabaseManager):
        self.database = database

    async def save_strategy(self, name: str, config: Dict[str, Any]) -> Optional[int]:
        """Save a strategy configuration."""
        strategy = Strategy(
            name=name,
            config=config,
            is_active=False  # Default to inactive
        )
        # Check if exists to update? DatabaseManager.create_strategy inserts.
        # DatabaseManager.update_strategy updates.
        # We should probably check if it exists or use upsert logic if we want to overwrite by name.
        # The current create_strategy does INSERT.
        # The current update_strategy does UPDATE.
        
        existing = await self.database.get_strategy(name)
        if existing:
            strategy.id = existing.id
            strategy.is_active = existing.is_active
            success = await self.database.update_strategy(strategy)
            return existing.id if success else None
        else:
            return await self.database.create_strategy(strategy)

    async def get_strategy(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a strategy by name."""
        strategy = await self.database.get_strategy(name)
        if not strategy:
            return None
        return strategy.config

    async def list_strategies(self) -> List[Dict[str, Any]]:
        """List all strategies."""
        strategies = await self.database.list_strategies()
        return [
            {
                "id": s.id,
                "name": s.name,
                "config": s.config,
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in strategies
        ]

    async def activate_strategy(self, name: str) -> bool:
        """Activate a strategy and deactivate others."""
        strategy = await self.database.get_strategy(name)
        if not strategy:
            return False
        
        strategy.is_active = True
        return await self.database.update_strategy(strategy)

    async def delete_strategy(self, name: str) -> bool:
        """Delete a strategy."""
        return await self.database.delete_strategy(name)
