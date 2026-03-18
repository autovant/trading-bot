"""Persistence layer — SQLite-backed storage for trade history and portfolio state."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import aiosqlite

from .models import CopiedTrade, TradeStatus, TradeSide

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS copied_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_trade_id TEXT    NOT NULL,
    source_wallet   TEXT    NOT NULL,
    market_id       TEXT    NOT NULL,
    asset_id        TEXT    NOT NULL,
    side            TEXT    NOT NULL,
    price           REAL    NOT NULL,
    size            REAL    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'PENDING',
    order_id        TEXT,
    fill_price      REAL,
    fill_size       REAL,
    pnl             REAL,
    error           TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_copied_trades_source ON copied_trades(source_trade_id);
CREATE INDEX IF NOT EXISTS idx_copied_trades_status ON copied_trades(status);
CREATE INDEX IF NOT EXISTS idx_copied_trades_wallet ON copied_trades(source_wallet);

CREATE TABLE IF NOT EXISTS daily_stats (
    date            TEXT PRIMARY KEY,
    total_trades    INTEGER DEFAULT 0,
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    realized_pnl    REAL    DEFAULT 0.0,
    volume_usdc     REAL    DEFAULT 0.0
);
"""


class TradeStore:
    """Async SQLite store for copied trades and statistics."""

    def __init__(self, db_url: str = "sqlite:///data/trades.db") -> None:
        # Parse "sqlite:///path" to just "path"
        if db_url.startswith("sqlite:///"):
            self._db_path = db_url[len("sqlite:///"):]
        else:
            self._db_path = db_url
        self._db: Optional[aiosqlite.Connection] = None

    async def start(self) -> None:
        """Open the database and ensure schema exists."""
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            Path(db_dir).mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("Trade store initialized: %s", self._db_path)

    async def stop(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def save_trade(self, trade: CopiedTrade) -> int:
        """Insert a new copied trade record. Returns the row ID."""
        if not self._db:
            raise RuntimeError("Store not started")
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.execute(
            """
            INSERT INTO copied_trades
                (source_trade_id, source_wallet, market_id, asset_id,
                 side, price, size, status, order_id, fill_price, fill_size,
                 pnl, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.source_trade_id,
                trade.source_wallet,
                trade.market_id,
                trade.asset_id,
                trade.side.value,
                trade.price,
                trade.size,
                trade.status.value,
                trade.order_id,
                trade.fill_price,
                trade.fill_size,
                trade.pnl,
                trade.error,
                trade.created_at.isoformat(),
                now,
            ),
        ) as cursor:
            await self._db.commit()
            return cursor.lastrowid or 0

    async def update_trade_status(
        self, trade_id: int, status: TradeStatus, **kwargs: object
    ) -> None:
        """Update the status and optional fields of a trade."""
        if not self._db:
            return
        sets = ["status = ?", "updated_at = ?"]
        vals: list = [status.value, datetime.now(timezone.utc).isoformat()]
        for col in ("fill_price", "fill_size", "pnl", "error", "order_id"):
            if col in kwargs:
                sets.append(f"{col} = ?")
                vals.append(kwargs[col])
        vals.append(trade_id)
        await self._db.execute(
            f"UPDATE copied_trades SET {', '.join(sets)} WHERE id = ?",
            vals,
        )
        await self._db.commit()

    async def get_recent_trades(self, limit: int = 50) -> List[CopiedTrade]:
        """Fetch the most recent copied trades."""
        if not self._db:
            return []
        async with self._db.execute(
            "SELECT * FROM copied_trades ORDER BY id DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_trade(r) for r in rows]

    async def get_trades_by_wallet(self, wallet: str, limit: int = 50) -> List[CopiedTrade]:
        """Fetch trades copied from a specific source wallet."""
        if not self._db:
            return []
        async with self._db.execute(
            "SELECT * FROM copied_trades WHERE source_wallet = ? ORDER BY id DESC LIMIT ?",
            (wallet, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_trade(r) for r in rows]

    async def get_stats(self) -> dict:
        """Aggregate statistics across all trades."""
        if not self._db:
            return {}
        async with self._db.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'FILLED' THEN 1 ELSE 0 END) as filled,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(SUM(size * price), 0) as total_volume
            FROM copied_trades
            """
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return {}

    @staticmethod
    def _row_to_trade(row) -> CopiedTrade:
        """Convert a database row to a CopiedTrade model."""
        return CopiedTrade(
            id=row["id"],
            source_trade_id=row["source_trade_id"],
            source_wallet=row["source_wallet"],
            market_id=row["market_id"],
            asset_id=row["asset_id"],
            side=TradeSide(row["side"]),
            price=row["price"],
            size=row["size"],
            status=TradeStatus(row["status"]),
            order_id=row["order_id"],
            fill_price=row["fill_price"],
            fill_size=row["fill_size"],
            pnl=row["pnl"],
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
