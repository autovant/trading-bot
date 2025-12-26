"""
PostgreSQL and SQLite persistence for the trading platform with strict schemas and
idempotent upserts. Every record is tagged with ``mode`` (live/paper/replay)
and ``run_id`` for full auditability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

import aiosqlite
import asyncpg
from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

Mode = Literal["live", "paper", "replay", "backtest"]

def _log_query(query: str, args: Any = None):
    """Log SQL query for debugging."""
    if logger.isEnabledFor(logging.DEBUG):
        # Truncate long queries for display
        clean_query = " ".join(query.split())
        logger.debug(f"DB: {clean_query} | Args: {args}")


class DBModel(BaseModel):
    """Shared strict configuration for all DB models."""

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, from_attributes=True
    )


class Order(DBModel):
    id: Optional[int] = None
    client_id: str
    order_id: Optional[str] = None
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: str = "open"
    mode: Mode = "paper"
    run_id: str = "default"
    latency_ms: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_shadow: bool = False

    @field_validator("client_id", "run_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("client_id/run_id must be provided")
        return value


class Trade(DBModel):
    id: Optional[int] = None
    client_id: str
    trade_id: str
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    realized_pnl: float = 0.0
    mark_price: float = 0.0
    slippage_bps: float = 0.0
    achieved_vs_signal_bps: float = 0.0
    latency_ms: float = 0.0
    maker: bool = False
    mode: Mode = "paper"
    run_id: str = "default"
    timestamp: Optional[datetime] = None
    is_shadow: bool = False

    @field_validator("client_id", "trade_id", "order_id", "run_id")
    @classmethod
    def _ensure_value(cls, value: str) -> str:
        if not value:
            raise ValueError("required trade identifier missing")
        return value


class Position(DBModel):
    id: Optional[int] = None
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    percentage: float
    mode: Mode = "paper"
    run_id: str = "default"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PnLEntry(DBModel):
    id: Optional[int] = None
    symbol: str
    trade_id: str
    realized_pnl: float
    unrealized_pnl: float
    commission: float
    fees: float = 0.0
    funding: float = 0.0
    net_pnl: float
    balance: float
    mode: Mode = "paper"
    run_id: str = "default"
    timestamp: Optional[datetime] = None


class RiskSnapshot(DBModel):
    id: Optional[int] = None
    mode: Mode
    run_id: str
    crisis_mode: bool
    consecutive_losses: int
    drawdown: float
    volatility: float
    position_size_factor: float
    payload: Dict[str, Any]
    created_at: Optional[datetime] = None


class Strategy(DBModel):
    id: Optional[int] = None
    name: str
    config: Dict[str, Any]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = False


class ConfigVersion(DBModel):
    id: Optional[int] = None
    version: str
    config: str
    created_at: Optional[datetime] = None

    @field_validator("version")
    @classmethod
    def _ensure_version(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise ValueError("version must not be blank")
        return candidate


class DatabaseBackend:
    """Interface for database backends."""

    async def initialize(self) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def create_order(self, order: Order) -> Optional[int]:
        raise NotImplementedError

    async def update_order_status(
        self, order_id: str, status: str, *, is_shadow: bool = False
    ) -> bool:
        raise NotImplementedError

    async def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Order]:
        raise NotImplementedError

    async def create_trade(self, trade: Trade) -> Optional[int]:
        raise NotImplementedError

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        run_id: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Trade]:
        raise NotImplementedError

    async def update_position(self, position: Position) -> bool:
        raise NotImplementedError

    async def get_positions(
        self, mode: Optional[Mode] = None, run_id: Optional[str] = None
    ) -> List[Position]:
        raise NotImplementedError

    async def aggregate_daily_pnl(self, days: int = 60) -> List[PnLEntry]:
        return []

    async def add_pnl_entry(self, entry: PnLEntry) -> bool:
        return True



from src.config import DatabaseConfig

class PostgresBackend(DatabaseBackend):
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.pool: Optional[asyncpg.Pool] = None

    async def initialize(self) -> None:
        try:
            self.pool = await asyncpg.create_pool(
                self.config.url,
                min_size=self.config.min_pool_size,
                max_size=self.config.max_pool_size
            )
            await self._ensure_schema()
            logger.info("Database initialised (Postgres)")
        except Exception as exc:
            logger.error("Failed to initialise Postgres: %s", exc)
            raise

    async def _ensure_schema(self) -> None:
        if not self.pool:
            raise RuntimeError("Pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, order_id TEXT UNIQUE, run_id TEXT NOT NULL,
                    mode TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, order_type TEXT NOT NULL,
                    quantity DOUBLE PRECISION NOT NULL, price DOUBLE PRECISION, stop_price DOUBLE PRECISION,
                    status TEXT NOT NULL, latency_ms DOUBLE PRECISION, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS orders_shadow (LIKE orders INCLUDING ALL);

                CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_orders_shadow_status ON orders_shadow(status);
                
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, trade_id TEXT UNIQUE NOT NULL,
                    order_id TEXT NOT NULL, run_id TEXT NOT NULL, mode TEXT NOT NULL, symbol TEXT NOT NULL,
                    side TEXT NOT NULL, quantity DOUBLE PRECISION NOT NULL, price DOUBLE PRECISION NOT NULL,
                    commission DOUBLE PRECISION NOT NULL DEFAULT 0, fees DOUBLE PRECISION NOT NULL DEFAULT 0,
                    funding DOUBLE PRECISION NOT NULL DEFAULT 0, realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    mark_price DOUBLE PRECISION NOT NULL DEFAULT 0, slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 0,
                    achieved_vs_signal_bps DOUBLE PRECISION NOT NULL DEFAULT 0, latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                    maker BOOLEAN NOT NULL DEFAULT FALSE, timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);

                CREATE TABLE IF NOT EXISTS trades_shadow (LIKE trades INCLUDING ALL);

                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL, size DOUBLE PRECISION NOT NULL,
                    entry_price DOUBLE PRECISION NOT NULL, mark_price DOUBLE PRECISION NOT NULL,
                    unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0, percentage DOUBLE PRECISION NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL, run_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(symbol, mode, run_id)
                );
            """)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def create_order(self, order: Order) -> Optional[int]:
        if not self.pool:
            return None
        table = "orders_shadow" if order.is_shadow else "orders"
        query = f"""
            INSERT INTO {table} (client_id, order_id, run_id, mode, symbol, side, order_type, quantity, price, stop_price, status, latency_ms)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT(client_id) DO UPDATE SET order_id=excluded.order_id, quantity=excluded.quantity, price=excluded.price,
            stop_price=excluded.stop_price, status=excluded.status, latency_ms=excluded.latency_ms, updated_at=CURRENT_TIMESTAMP
            RETURNING id
        """
        _log_query(query, (order.client_id, order.order_id, order.run_id, order.mode, order.symbol, order.side, order.order_type, order.quantity, order.price, order.stop_price, order.status, order.latency_ms))
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                order.client_id,
                order.order_id,
                order.run_id,
                order.mode,
                order.symbol,
                order.side,
                order.order_type,
                order.quantity,
                order.price,
                order.stop_price,
                order.status,
                order.latency_ms,
            )

    async def update_order_status(
        self, order_id: str, status: str, *, is_shadow: bool = False
    ) -> bool:
        if not self.pool:
            return False
        table = "orders_shadow" if is_shadow else "orders"
        query = f"UPDATE {table} SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE order_id = $2"
        async with self.pool.acquire() as conn:
            res = await conn.execute(query, status, order_id)
            return int(res.split(" ")[-1]) > 0

    async def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Order]:
        if not self.pool:
            return []
        table = "orders_shadow" if is_shadow else "orders"
        query = f"SELECT * FROM {table} WHERE 1=1"
        args = []
        if symbol:
            args.append(symbol)
            query += f" AND symbol = ${len(args)}"
        if status:
            args.append(status)
            query += f" AND status = ${len(args)}"
        query += " ORDER BY created_at DESC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [Order(**row) for row in rows]

    async def create_trade(self, trade: Trade) -> Optional[int]:
        if not self.pool:
            return None
        table = "trades_shadow" if trade.is_shadow else "trades"
        query = f"""
            INSERT INTO {table} (client_id, trade_id, order_id, run_id, mode, symbol, side, quantity, price,
            commission, fees, funding, realized_pnl, mark_price, slippage_bps, achieved_vs_signal_bps, latency_ms, maker, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            ON CONFLICT(client_id) DO UPDATE SET price=excluded.price, commission=excluded.commission, fees=excluded.fees,
            funding=excluded.funding, realized_pnl=excluded.realized_pnl, mark_price=excluded.mark_price, slippage_bps=excluded.slippage_bps,
            achieved_vs_signal_bps=excluded.achieved_vs_signal_bps, latency_ms=excluded.latency_ms, maker=excluded.maker, timestamp=excluded.timestamp
            RETURNING id
            RETURNING id
        """
        _log_query(query, (trade.client_id, trade.trade_id, trade.order_id, trade.run_id, trade.mode, trade.symbol, trade.side, trade.quantity, trade.price, trade.commission, trade.fees, trade.funding, trade.realized_pnl, trade.mark_price, trade.slippage_bps, trade.achieved_vs_signal_bps, trade.latency_ms, trade.maker, trade.timestamp or datetime.now(timezone.utc)))
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                trade.client_id,
                trade.trade_id,
                trade.order_id,
                trade.run_id,
                trade.mode,
                trade.symbol,
                trade.side,
                trade.quantity,
                trade.price,
                trade.commission,
                trade.fees,
                trade.funding,
                trade.realized_pnl,
                trade.mark_price,
                trade.slippage_bps,
                trade.achieved_vs_signal_bps,
                trade.latency_ms,
                trade.maker,
                trade.timestamp or datetime.now(timezone.utc),
            )

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        run_id: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Trade]:
        if not self.pool:
            return []
        table = "trades_shadow" if is_shadow else "trades"
        query = f"SELECT * FROM {table} WHERE 1=1"
        args = []
        if symbol:
            args.append(symbol)
            query += f" AND symbol = ${len(args)}"
        if run_id:
            args.append(run_id)
            query += f" AND run_id = ${len(args)}"
        args.append(limit)
        query += f" ORDER BY timestamp DESC LIMIT ${len(args)}"
        
        _log_query(query, args)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [Trade(**row) for row in rows]

    async def update_position(self, position: Position) -> bool:
        if not self.pool:
            return False
        query = """
            INSERT INTO positions (symbol, side, size, entry_price, mark_price, unrealized_pnl, percentage, mode, run_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT(symbol, mode, run_id) DO UPDATE SET side=excluded.side, size=excluded.size, entry_price=excluded.entry_price,
            mark_price=excluded.mark_price, unrealized_pnl=excluded.unrealized_pnl, percentage=excluded.percentage, updated_at=CURRENT_TIMESTAMP
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                position.symbol,
                position.side,
                position.size,
                position.entry_price,
                position.mark_price,
                position.unrealized_pnl,
                position.percentage,
                position.mode,
                position.run_id,
            )
            return True

    async def get_positions(
        self, mode: Optional[Mode] = None, run_id: Optional[str] = None
    ) -> List[Position]:
        if not self.pool:
            return []
        query = "SELECT * FROM positions WHERE 1=1"
        args = []
        if mode:
            args.append(mode)
            query += f" AND mode = ${len(args)}"
        if run_id:
            args.append(run_id)
            query += f" AND run_id = ${len(args)}"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [Position(**row) for row in rows]


class SQLiteBackend(DatabaseBackend):
    def __init__(self, config: DatabaseConfig):
        self.db_path = config.url.replace("sqlite:///", "")
        self.conn: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        try:
            self.conn = await aiosqlite.connect(self.db_path)
            self.conn.row_factory = aiosqlite.Row
            await self.conn.execute("PRAGMA journal_mode=WAL;")
            await self._ensure_schema()
            logger.info("Database initialised (SQLite)")
        except Exception as exc:
            logger.error("Failed to initialise SQLite: %s", exc)
            raise

    async def _ensure_schema(self) -> None:
        if not self.conn:
            raise RuntimeError("SQLite not connected")
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT UNIQUE NOT NULL, order_id TEXT UNIQUE, run_id TEXT NOT NULL,
                mode TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, order_type TEXT NOT NULL,
                quantity REAL NOT NULL, price REAL, stop_price REAL, status TEXT NOT NULL, latency_ms REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders_shadow (
                id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT UNIQUE NOT NULL, order_id TEXT UNIQUE, run_id TEXT NOT NULL,
                mode TEXT NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, order_type TEXT NOT NULL,
                quantity REAL NOT NULL, price REAL, stop_price REAL, status TEXT NOT NULL, latency_ms REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_orders_shadow_status ON orders_shadow(status); 
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT UNIQUE NOT NULL, trade_id TEXT UNIQUE NOT NULL,
                order_id TEXT NOT NULL, run_id TEXT NOT NULL, mode TEXT NOT NULL, symbol TEXT NOT NULL,
                side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, commission REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0, funding REAL NOT NULL DEFAULT 0, realized_pnl REAL NOT NULL DEFAULT 0,
                mark_price REAL NOT NULL DEFAULT 0, slippage_bps REAL NOT NULL DEFAULT 0, achieved_vs_signal_bps REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0, maker BOOLEAN NOT NULL DEFAULT 0, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS trades_shadow (
                id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT UNIQUE NOT NULL, trade_id TEXT UNIQUE NOT NULL,
                order_id TEXT NOT NULL, run_id TEXT NOT NULL, mode TEXT NOT NULL, symbol TEXT NOT NULL,
                side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, commission REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0, funding REAL NOT NULL DEFAULT 0, realized_pnl REAL NOT NULL DEFAULT 0,
                mark_price REAL NOT NULL DEFAULT 0, slippage_bps REAL NOT NULL DEFAULT 0, achieved_vs_signal_bps REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0, maker BOOLEAN NOT NULL DEFAULT 0, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
            CREATE INDEX IF NOT EXISTS idx_trades_shadow_timestamp ON trades_shadow(timestamp);
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, side TEXT NOT NULL, size REAL NOT NULL,
                entry_price REAL NOT NULL, mark_price REAL NOT NULL, unrealized_pnl REAL NOT NULL DEFAULT 0,
                percentage REAL NOT NULL DEFAULT 0, mode TEXT NOT NULL, run_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, mode, run_id)
            );
        """)

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def create_order(self, order: Order) -> Optional[int]:
        if not self.conn:
            return None
        table = "orders_shadow" if order.is_shadow else "orders"
        query = f"""
            INSERT INTO {table} (client_id, order_id, run_id, mode, symbol, side, order_type, quantity, price, stop_price, status, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET order_id=excluded.order_id, quantity=excluded.quantity, price=excluded.price,
            stop_price=excluded.stop_price, status=excluded.status, latency_ms=excluded.latency_ms, updated_at=CURRENT_TIMESTAMP
        """
        try:
            params = (
                order.client_id,
                order.order_id,
                order.run_id,
                order.mode,
                order.symbol,
                order.side,
                order.order_type,
                order.quantity,
                order.price,
                order.stop_price,
                order.status,
                order.latency_ms,
            )
            _log_query(query, params)
            cursor = await self.conn.execute(
                query,
                params,
            )
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_order failed: %s", e)
            return None

    async def update_order_status(
        self, order_id: str, status: str, *, is_shadow: bool = False
    ) -> bool:
        if not self.conn:
            return False
        table = "orders_shadow" if is_shadow else "orders"
        cursor = await self.conn.execute(
            f"UPDATE {table} SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE order_id = ?",
            (status, order_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Order]:
        if not self.conn:
            return []
        table = "orders_shadow" if is_shadow else "orders"
        query = f"SELECT * FROM {table} WHERE 1=1"
        args = []
        if symbol:
            args.append(symbol)
            query += " AND symbol = ?"
        if status:
            args.append(status)
            query += " AND status = ?"
        query += " ORDER BY created_at DESC"
        async with self.conn.execute(query, tuple(args)) as cursor:
            rows = await cursor.fetchall()
            return [Order(**dict(row)) for row in rows]

    async def create_trade(self, trade: Trade) -> Optional[int]:
        if not self.conn:
            return None
        table = "trades_shadow" if trade.is_shadow else "trades"
        query = f"""
            INSERT INTO {table} (client_id, trade_id, order_id, run_id, mode, symbol, side, quantity, price,
            commission, fees, funding, realized_pnl, mark_price, slippage_bps, achieved_vs_signal_bps, latency_ms, maker, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET price=excluded.price, commission=excluded.commission, fees=excluded.fees,
            funding=excluded.funding, realized_pnl=excluded.realized_pnl, mark_price=excluded.mark_price, slippage_bps=excluded.slippage_bps,
            achieved_vs_signal_bps=excluded.achieved_vs_signal_bps, latency_ms=excluded.latency_ms, maker=excluded.maker, timestamp=excluded.timestamp
        """
        try:
            ts = trade.timestamp or datetime.now(timezone.utc)
            params = (
                trade.client_id,
                trade.trade_id,
                trade.order_id,
                trade.run_id,
                trade.mode,
                trade.symbol,
                trade.side,
                trade.quantity,
                trade.price,
                trade.commission,
                trade.fees,
                trade.funding,
                trade.realized_pnl,
                trade.mark_price,
                trade.slippage_bps,
                trade.achieved_vs_signal_bps,
                trade.latency_ms,
                trade.maker,
                ts,
            )
            _log_query(query, params)
            cursor = await self.conn.execute(query, params)
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_trade failed: %s", e)
            return None

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        run_id: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Trade]:
        if not self.conn:
            return []
        table = "trades_shadow" if is_shadow else "trades"
        query = f"SELECT * FROM {table} WHERE 1=1"
        args = []
        if symbol:
            args.append(symbol)
            query += " AND symbol = ?"
        if run_id:
            args.append(run_id)
            query += " AND run_id = ?"
        args.append(limit)
        query += " ORDER BY timestamp DESC LIMIT ?"
        
        _log_query(query, args)
        async with self.conn.execute(query, tuple(args)) as cursor:
            rows = await cursor.fetchall()
            return [Trade(**dict(row)) for row in rows]

    async def update_position(self, position: Position) -> bool:
        if not self.conn:
            return False
        query = """
            INSERT INTO positions (symbol, side, size, entry_price, mark_price, unrealized_pnl, percentage, mode, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, mode, run_id) DO UPDATE SET side=excluded.side, size=excluded.size, entry_price=excluded.entry_price,
            mark_price=excluded.mark_price, unrealized_pnl=excluded.unrealized_pnl, percentage=excluded.percentage, updated_at=CURRENT_TIMESTAMP
        """
        try:
            await self.conn.execute(
                query,
                (
                    position.symbol,
                    position.side,
                    position.size,
                    position.entry_price,
                    position.mark_price,
                    position.unrealized_pnl,
                    position.percentage,
                    position.mode,
                    position.run_id,
                ),
            )
            await self.conn.commit()
            return True
        except Exception as e:
            logger.error("SQLite update_position failed: %s", e)
            return False

    async def get_positions(
        self, mode: Optional[Mode] = None, run_id: Optional[str] = None
    ) -> List[Position]:
        if not self.conn:
            return []
        query = "SELECT * FROM positions WHERE 1=1"
        args = []
        if mode:
            args.append(mode)
            query += " AND mode = ?"
        if run_id:
            args.append(run_id)
            query += " AND run_id = ?"
        async with self.conn.execute(query, tuple(args)) as cursor:
            rows = await cursor.fetchall()
            return [Position(**dict(row)) for row in rows]


class DatabaseManager:
    """Facade for database backends."""

    def __init__(self, config: Union[str, DatabaseConfig]):
        if isinstance(config, str):
            self.config = DatabaseConfig(url=config)
        else:
            self.config = config
        self.backend: Optional[DatabaseBackend] = None

    async def initialize(self) -> None:
        if "postgres" in self.config.url:
            self.backend = PostgresBackend(self.config)
        else:
            self.backend = SQLiteBackend(self.config)
        await self.backend.initialize()

    async def close(self) -> None:
        if self.backend:
            await self.backend.close()

    async def create_order(self, order: Order) -> Optional[int]:
        if self.backend:
            return await self.backend.create_order(order)
        return None

    async def update_order_status(
        self, order_id: str, status: str, *, is_shadow: bool = False
    ) -> bool:
        if self.backend:
            return await self.backend.update_order_status(
                order_id, status, is_shadow=is_shadow
            )
        return False

    async def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Order]:
        if self.backend:
            return await self.backend.get_orders(symbol, status, is_shadow=is_shadow)
        return []

    async def create_trade(self, trade: Trade) -> Optional[int]:
        if self.backend:
            return await self.backend.create_trade(trade)
        return None

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        run_id: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Trade]:
        if self.backend:
            return await self.backend.get_trades(
                symbol, limit, run_id, is_shadow=is_shadow
            )
        return []

    async def update_position(self, position: Position) -> bool:
        if self.backend:
            return await self.backend.update_position(position)
        return False

    async def get_positions(
        self, mode: Optional[Mode] = None, run_id: Optional[str] = None
    ) -> List[Position]:
        if self.backend:
            return await self.backend.get_positions(mode, run_id)
        return []

    async def aggregate_daily_pnl(self, days: int = 60) -> List[PnLEntry]:
        if self.backend:
            return await self.backend.aggregate_daily_pnl(days)
        return []

    async def add_pnl_entry(self, entry: PnLEntry) -> bool:
        if self.backend:
            return await self.backend.add_pnl_entry(entry)
        return True
