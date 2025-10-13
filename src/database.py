"""
SQLite persistence for the trading platform with strict schemas and
idempotent upserts. Every record is tagged with ``mode`` (live/paper/replay)
and ``run_id`` for full auditability.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

Mode = Literal["live", "paper", "replay"]


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


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0


def _row_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class DatabaseManager:
    """SQLite database manager with schema enforcement."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.connection: Optional[sqlite3.Connection] = None

    async def initialize(self) -> None:
        """Initialise the SQLite database connection and schema."""

        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA journal_mode=WAL;")
            self._ensure_schema()
            logger.info("Database initialised at %s", self.db_path)
        except Exception as exc:
            logger.error("Failed to initialise database: %s", exc)
            raise

    def _ensure_schema(self) -> None:
        if not self.connection:
            raise RuntimeError("database connection not initialised")

        cursor = self.connection.cursor()

        # Core tables
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                order_id TEXT UNIQUE,
                run_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL,
                stop_price REAL,
                status TEXT NOT NULL,
                latency_ms REAL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orders_shadow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                order_id TEXT UNIQUE,
                run_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL,
                stop_price REAL,
                status TEXT NOT NULL,
                latency_ms REAL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                trade_id TEXT UNIQUE NOT NULL,
                order_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0,
                funding REAL NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0,
                mark_price REAL NOT NULL DEFAULT 0,
                slippage_bps REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                maker INTEGER NOT NULL DEFAULT 0,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades_shadow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT UNIQUE NOT NULL,
                trade_id TEXT UNIQUE NOT NULL,
                order_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0,
                funding REAL NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0,
                mark_price REAL NOT NULL DEFAULT 0,
                slippage_bps REAL NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                maker INTEGER NOT NULL DEFAULT 0,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                size REAL NOT NULL,
                entry_price REAL NOT NULL,
                mark_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL DEFAULT 0,
                percentage REAL NOT NULL DEFAULT 0,
                mode TEXT NOT NULL,
                run_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, mode, run_id)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pnl_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                realized_pnl REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                commission REAL NOT NULL,
                fees REAL NOT NULL DEFAULT 0,
                funding REAL NOT NULL DEFAULT 0,
                net_pnl REAL NOT NULL,
                balance REAL NOT NULL,
                mode TEXT NOT NULL,
                run_id TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(trade_id, run_id, mode)
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                run_id TEXT NOT NULL,
                crisis_mode INTEGER NOT NULL,
                consecutive_losses INTEGER NOT NULL,
                drawdown REAL NOT NULL,
                volatility REAL NOT NULL,
                position_size_factor REAL NOT NULL,
                payload TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_performance (
                mode TEXT PRIMARY KEY,
                run_id TEXT,
                total_trades INTEGER DEFAULT 0,
                winning_trades INTEGER DEFAULT 0,
                losing_trades INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                profit_factor REAL DEFAULT 0,
                sharpe_ratio REAL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS config_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                config TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Indexes for faster queries
        for table, column in [
            ("orders", "symbol"),
            ("orders", "mode"),
            ("orders_shadow", "symbol"),
            ("orders_shadow", "mode"),
            ("trades", "symbol"),
            ("trades", "mode"),
            ("trades", "timestamp"),
            ("trades_shadow", "symbol"),
            ("trades_shadow", "mode"),
            ("trades_shadow", "timestamp"),
            ("positions", "mode"),
            ("positions", "symbol"),
            ("pnl_ledger", "mode"),
            ("pnl_ledger", "timestamp"),
            ("risk_snapshots", "mode"),
            ("risk_snapshots", "created_at"),
        ]:
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_{column} ON {table} ({column})"
            )

        self.connection.commit()

    async def close(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    # --------------------------------------------------------------------- #
    # Orders
    # --------------------------------------------------------------------- #

    async def create_order(self, order: Order) -> Optional[int]:
        if not self.connection:
            return None
        try:
            cursor = self.connection.cursor()
            table = "orders_shadow" if order.is_shadow else "orders"
            cursor.execute(
                f"""
                INSERT INTO {table}
                (client_id, order_id, run_id, mode, symbol, side, order_type,
                 quantity, price, stop_price, status, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    order_id = excluded.order_id,
                    quantity = excluded.quantity,
                    price = excluded.price,
                    stop_price = excluded.stop_price,
                    status = excluded.status,
                    latency_ms = excluded.latency_ms,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (
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
                ),
            )
            self.connection.commit()
            return cursor.lastrowid
        except Exception as exc:
            logger.error("Error creating order: %s", exc)
            return None

    async def update_order_status(
        self, order_id: str, status: str, *, is_shadow: bool = False
    ) -> bool:
        if not self.connection:
            return False
        try:
            cursor = self.connection.cursor()
            table = "orders_shadow" if is_shadow else "orders"
            cursor.execute(
                f"""
                UPDATE {table}
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
            """,
                (status, order_id),
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Error updating order status: %s", exc)
            return False

    async def get_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        *,
        is_shadow: bool = False,
    ) -> List[Order]:
        if not self.connection:
            return []

        try:
            cursor = self.connection.cursor()
            table = "orders_shadow" if is_shadow else "orders"
            query = f"SELECT * FROM {table} WHERE 1=1"
            params: List[Any] = []

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                Order(
                    id=row["id"],
                    client_id=row["client_id"],
                    order_id=row["order_id"],
                    symbol=row["symbol"],
                    side=row["side"],
                    order_type=row["order_type"],
                    quantity=row["quantity"],
                    price=row["price"],
                    stop_price=row["stop_price"],
                    status=row["status"],
                    mode=row["mode"],
                    run_id=row["run_id"],
                    latency_ms=row["latency_ms"],
                    created_at=_row_datetime(row["created_at"]),
                    updated_at=_row_datetime(row["updated_at"]),
                    is_shadow=is_shadow,
                )
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error fetching orders: %s", exc)
            return []

    # --------------------------------------------------------------------- #
    # Trades
    # --------------------------------------------------------------------- #

    async def create_trade(self, trade: Trade) -> Optional[int]:
        if not self.connection:
            return None

        try:
            cursor = self.connection.cursor()
            table = "trades_shadow" if trade.is_shadow else "trades"
            cursor.execute(
                f"""
                INSERT INTO {table}
                (client_id, trade_id, order_id, run_id, mode, symbol, side, quantity,
                 price, commission, fees, funding, realized_pnl, mark_price,
                 slippage_bps, latency_ms, maker, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    price = excluded.price,
                    commission = excluded.commission,
                    fees = excluded.fees,
                    funding = excluded.funding,
                    realized_pnl = excluded.realized_pnl,
                    mark_price = excluded.mark_price,
                    slippage_bps = excluded.slippage_bps,
                    latency_ms = excluded.latency_ms,
                    maker = excluded.maker,
                    timestamp = excluded.timestamp
            """,
                (
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
                    trade.latency_ms,
                    _bool_to_int(trade.maker),
                    (trade.timestamp or datetime.utcnow()).isoformat(),
                ),
            )
            self.connection.commit()
            return cursor.lastrowid
        except Exception as exc:
            logger.error("Error creating trade: %s", exc)
            return None

    async def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        *,
        is_shadow: bool = False,
    ) -> List[Trade]:
        if not self.connection:
            return []
        try:
            cursor = self.connection.cursor()
            table = "trades_shadow" if is_shadow else "trades"
            query = f"SELECT * FROM {table} WHERE 1=1"
            params: List[Any] = []

            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                Trade(
                    id=row["id"],
                    client_id=row["client_id"],
                    trade_id=row["trade_id"],
                    order_id=row["order_id"],
                    symbol=row["symbol"],
                    side=row["side"],
                    quantity=row["quantity"],
                    price=row["price"],
                    commission=row["commission"],
                    fees=row["fees"],
                    funding=row["funding"],
                    realized_pnl=row["realized_pnl"],
                    mark_price=row["mark_price"],
                    slippage_bps=row["slippage_bps"],
                    latency_ms=row["latency_ms"],
                    maker=bool(row["maker"]),
                    mode=row["mode"],
                    run_id=row["run_id"],
                    timestamp=_row_datetime(row["timestamp"]),
                    is_shadow=is_shadow,
                )
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error fetching trades: %s", exc)
            return []

    # --------------------------------------------------------------------- #
    # Positions
    # --------------------------------------------------------------------- #

    async def update_position(self, position: Position) -> bool:
        if not self.connection:
            return False

        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO positions
                (symbol, side, size, entry_price, mark_price, unrealized_pnl,
                 percentage, mode, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, mode, run_id) DO UPDATE SET
                    side = excluded.side,
                    size = excluded.size,
                    entry_price = excluded.entry_price,
                    mark_price = excluded.mark_price,
                    unrealized_pnl = excluded.unrealized_pnl,
                    percentage = excluded.percentage,
                    updated_at = CURRENT_TIMESTAMP
            """,
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
            self.connection.commit()
            return True
        except Exception as exc:
            logger.error("Error updating position: %s", exc)
            return False

    async def get_positions(
        self, mode: Optional[Mode] = None, run_id: Optional[str] = None
    ) -> List[Position]:
        if not self.connection:
            return []
        try:
            cursor = self.connection.cursor()
            query = "SELECT * FROM positions WHERE 1=1"
            params: List[Any] = []

            if mode:
                query += " AND mode = ?"
                params.append(mode)
            if run_id:
                query += " AND run_id = ?"
                params.append(run_id)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [
                Position(
                    id=row["id"],
                    symbol=row["symbol"],
                    side=row["side"],
                    size=row["size"],
                    entry_price=row["entry_price"],
                    mark_price=row["mark_price"],
                    unrealized_pnl=row["unrealized_pnl"],
                    percentage=row["percentage"],
                    mode=row["mode"],
                    run_id=row["run_id"],
                    created_at=_row_datetime(row["created_at"]),
                    updated_at=_row_datetime(row["updated_at"]),
                )
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error fetching positions: %s", exc)
            return []

    # --------------------------------------------------------------------- #
    # Config versions
    # --------------------------------------------------------------------- #

    async def upsert_config_version(self, version: str, config_blob: str) -> bool:
        if not self.connection:
            return False

        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO config_versions (version, config)
                VALUES (?, ?)
                ON CONFLICT(version) DO UPDATE SET
                    config = excluded.config,
                    created_at = CURRENT_TIMESTAMP
                """,
                (version, config_blob),
            )
            self.connection.commit()
            return True
        except Exception as exc:
            logger.error("Error saving config version %s: %s", version, exc)
            return False

    async def get_config_version(self, version: str) -> Optional[ConfigVersion]:
        if not self.connection:
            return None

        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT id, version, config, created_at
                FROM config_versions
                WHERE version = ?
                """,
                (version,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return ConfigVersion(
                id=row["id"],
                version=row["version"],
                config=row["config"],
                created_at=_row_datetime(row["created_at"]),
            )
        except Exception as exc:
            logger.error("Error fetching config version %s: %s", version, exc)
            return None

    async def list_config_versions(
        self, limit: int = 20
    ) -> List[ConfigVersion]:
        if not self.connection:
            return []

        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT id, version, config, created_at
                FROM config_versions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                ConfigVersion(
                    id=row["id"],
                    version=row["version"],
                    config=row["config"],
                    created_at=_row_datetime(row["created_at"]),
                )
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error listing config versions: %s", exc)
            return []


    # --------------------------------------------------------------------- #
    # PnL Ledger
    # --------------------------------------------------------------------- #

    async def aggregate_daily_pnl(self, days: int = 60) -> List[PnLEntry]:
        entries = await self.get_pnl_history(days=days)
        if not entries:
            return []

        buckets: Dict[tuple[str, Mode, str], Dict[str, Any]] = {}

        for entry in entries:
            if entry.trade_id and entry.trade_id.startswith("rollup-"):
                continue
            if entry.timestamp is None:
                continue

            key = (entry.timestamp.date().isoformat(), entry.mode, entry.run_id)
            bucket = buckets.setdefault(
                key,
                {
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "commission": 0.0,
                    "fees": 0.0,
                    "funding": 0.0,
                    "net_pnl": 0.0,
                    "balance": 0.0,
                    "latest_ts": entry.timestamp,
                },
            )

            bucket["realized_pnl"] += entry.realized_pnl
            bucket["unrealized_pnl"] += entry.unrealized_pnl
            bucket["commission"] += entry.commission
            bucket["fees"] += entry.fees
            bucket["funding"] += entry.funding
            bucket["net_pnl"] += entry.net_pnl

            if entry.timestamp >= bucket["latest_ts"]:
                bucket["latest_ts"] = entry.timestamp
                bucket["balance"] = entry.balance

        summaries: List[PnLEntry] = []
        for (day, mode, run_id), stats in buckets.items():
            timestamp = stats["latest_ts"].replace(
                hour=23, minute=59, second=59, microsecond=0
            )
            trade_id = f"rollup-{mode}-{run_id}-{day}"
            summaries.append(
                PnLEntry(
                    symbol="ALL",
                    trade_id=trade_id,
                    realized_pnl=stats["realized_pnl"],
                    unrealized_pnl=stats["unrealized_pnl"],
                    commission=stats["commission"],
                    fees=stats["fees"],
                    funding=stats["funding"],
                    net_pnl=stats["net_pnl"],
                    balance=stats["balance"],
                    mode=mode,
                    run_id=run_id,
                    timestamp=timestamp,
                )
            )

        summaries.sort(key=lambda item: item.timestamp or datetime.utcnow())
        return summaries

    async def add_pnl_entry(self, entry: PnLEntry) -> Optional[int]:
        if not self.connection:
            return None
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO pnl_ledger
                (symbol, trade_id, realized_pnl, unrealized_pnl, commission, fees,
                 funding, net_pnl, balance, mode, run_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id, run_id, mode) DO UPDATE SET
                    realized_pnl = excluded.realized_pnl,
                    unrealized_pnl = excluded.unrealized_pnl,
                    commission = excluded.commission,
                    fees = excluded.fees,
                    funding = excluded.funding,
                    net_pnl = excluded.net_pnl,
                    balance = excluded.balance,
                    timestamp = excluded.timestamp
            """,
                (
                    entry.symbol,
                    entry.trade_id,
                    entry.realized_pnl,
                    entry.unrealized_pnl,
                    entry.commission,
                    entry.fees,
                    entry.funding,
                    entry.net_pnl,
                    entry.balance,
                    entry.mode,
                    entry.run_id,
                    (entry.timestamp or datetime.utcnow()).isoformat(),
                ),
            )
            self.connection.commit()
            return cursor.lastrowid
        except Exception as exc:
            logger.error("Error adding PnL entry: %s", exc)
            return None

    async def get_pnl_history(
        self, days: int = 30, mode: Optional[Mode] = None
    ) -> List[PnLEntry]:
        if not self.connection:
            return []
        try:
            cursor = self.connection.cursor()
            query = """
                SELECT * FROM pnl_ledger
                WHERE timestamp >= datetime('now', ?)
            """
            params: List[Any] = [f"-{int(days)} days"]
            if mode:
                query += " AND mode = ?"
                params.append(mode)
            query += " ORDER BY timestamp DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [
                PnLEntry(
                    id=row["id"],
                    symbol=row["symbol"],
                    trade_id=row["trade_id"],
                    realized_pnl=row["realized_pnl"],
                    unrealized_pnl=row["unrealized_pnl"],
                    commission=row["commission"],
                    fees=row["fees"],
                    funding=row["funding"],
                    net_pnl=row["net_pnl"],
                    balance=row["balance"],
                    mode=row["mode"],
                    run_id=row["run_id"],
                    timestamp=_row_datetime(row["timestamp"]),
                )
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error retrieving PnL history: %s", exc)
            return []

    # --------------------------------------------------------------------- #
    # Risk snapshots
    # --------------------------------------------------------------------- #

    async def record_risk_snapshot(
        self, snapshot: Dict[str, Any], *, mode: Mode, run_id: str
    ) -> bool:
        if not self.connection:
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO risk_snapshots
                (mode, run_id, crisis_mode, consecutive_losses, drawdown, volatility,
                 position_size_factor, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    mode,
                    run_id,
                    _bool_to_int(bool(snapshot.get("crisis_mode", False))),
                    int(snapshot.get("consecutive_losses", 0)),
                    float(snapshot.get("drawdown", 0.0)),
                    float(snapshot.get("volatility", 0.0)),
                    float(snapshot.get("position_size_factor", 0.0)),
                    json.dumps(snapshot),
                ),
            )
            self.connection.commit()
            return True
        except Exception as exc:
            logger.error("Error recording risk snapshot: %s", exc)
            return False

    async def get_risk_snapshots(self, limit: int = 50) -> List[RiskSnapshot]:
        if not self.connection:
            return []
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT id, mode, run_id, crisis_mode, consecutive_losses, drawdown,
                       volatility, position_size_factor, payload, created_at
                FROM risk_snapshots
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )
            rows = cursor.fetchall()
            snapshots: List[RiskSnapshot] = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                snapshots.append(
                    RiskSnapshot(
                        id=row["id"],
                        mode=row["mode"],
                        run_id=row["run_id"],
                        crisis_mode=bool(row["crisis_mode"]),
                        consecutive_losses=row["consecutive_losses"],
                        drawdown=row["drawdown"],
                        volatility=row["volatility"],
                        position_size_factor=row["position_size_factor"],
                        payload=payload,
                        created_at=_row_datetime(row["created_at"]),
                    )
                )
            return snapshots
        except Exception as exc:
            logger.error("Error retrieving risk snapshots: %s", exc)
            return []

    # --------------------------------------------------------------------- #
    # Performance metrics
    # --------------------------------------------------------------------- #

    async def update_performance_metrics(
        self, metrics: Dict[str, Any], mode: Mode = "paper", run_id: str = "default"
    ) -> bool:
        if not self.connection:
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO strategy_performance
                (mode, run_id, total_trades, winning_trades, losing_trades,
                 total_pnl, max_drawdown, win_rate, profit_factor, sharpe_ratio, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(mode) DO UPDATE SET
                    run_id = excluded.run_id,
                    total_trades = excluded.total_trades,
                    winning_trades = excluded.winning_trades,
                    losing_trades = excluded.losing_trades,
                    total_pnl = excluded.total_pnl,
                    max_drawdown = excluded.max_drawdown,
                    win_rate = excluded.win_rate,
                    profit_factor = excluded.profit_factor,
                    sharpe_ratio = excluded.sharpe_ratio,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (
                    mode,
                    run_id,
                    metrics.get("total_trades", 0),
                    metrics.get("winning_trades", 0),
                    metrics.get("losing_trades", 0),
                    metrics.get("total_pnl", 0.0),
                    metrics.get("max_drawdown", 0.0),
                    metrics.get("win_rate", 0.0),
                    metrics.get("profit_factor", 0.0),
                    metrics.get("sharpe_ratio", 0.0),
                ),
            )
            self.connection.commit()
            return True
        except Exception as exc:
            logger.error("Error updating performance metrics: %s", exc)
            return False

    async def get_performance_metrics(
        self, mode: Mode = "paper"
    ) -> Optional[Dict[str, Any]]:
        if not self.connection:
            return None

        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT * FROM strategy_performance WHERE mode = ?
            """,
                (mode,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return {
                "mode": row["mode"],
                "run_id": row["run_id"],
                "total_trades": row["total_trades"],
                "winning_trades": row["winning_trades"],
                "losing_trades": row["losing_trades"],
                "total_pnl": row["total_pnl"],
                "max_drawdown": row["max_drawdown"],
                "win_rate": row["win_rate"],
                "profit_factor": row["profit_factor"],
                "sharpe_ratio": row["sharpe_ratio"],
                "updated_at": row["updated_at"],
            }
        except Exception as exc:
            logger.error("Error retrieving performance metrics: %s", exc)
            return None
