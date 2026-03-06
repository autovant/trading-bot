"""
PostgreSQL and SQLite persistence for the trading platform with strict schemas and
idempotent upserts. Every record is tagged with ``mode`` (live/paper/replay)
and ``run_id`` for full auditability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Union

import aiosqlite
import asyncpg
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import DatabaseConfig

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


class OrderIntent(DBModel):
    id: Optional[int] = None
    idempotency_key: str
    client_id: str
    order_id: Optional[str] = None
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    reduce_only: bool = False
    status: str = "created"
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    last_error: Optional[str] = None
    mode: Mode = "paper"
    run_id: str = "default"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("idempotency_key", "client_id", "run_id")
    @classmethod
    def _intent_key_present(cls, value: str) -> str:
        if not value:
            raise ValueError("idempotency_key/client_id/run_id must be provided")
        return value


class OrderIntentEvent(DBModel):
    id: Optional[int] = None
    idempotency_key: str
    status: str
    details: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_validator("idempotency_key", "status")
    @classmethod
    def _intent_event_present(cls, value: str) -> str:
        if not value:
            raise ValueError("intent event fields must be provided")
        return value


class OrderFill(DBModel):
    id: Optional[int] = None
    idempotency_key: str
    trade_id: str
    order_id: Optional[str] = None
    symbol: str
    side: str
    quantity: float
    price: float
    fee: float = 0.0
    timestamp: Optional[datetime] = None

    @field_validator("idempotency_key", "trade_id")
    @classmethod
    def _fill_identifiers_present(cls, value: str) -> str:
        if not value:
            raise ValueError("fill identifiers must be provided")
        return value


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


AgentStatus = Literal["created", "backtesting", "paper", "live", "paused", "retired"]


class Agent(DBModel):
    id: Optional[int] = None
    name: str
    status: AgentStatus = "created"
    config_json: Dict[str, Any] = Field(default_factory=dict)
    allocation_usd: float = 0.0
    strategy_name: Optional[str] = None
    strategy_params: Optional[str] = None  # JSON-serialized
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    retired_at: Optional[datetime] = None


class AgentDecision(DBModel):
    id: Optional[int] = None
    agent_id: int
    timestamp: Optional[datetime] = None
    phase: Literal["observe", "orient", "decide", "act", "learn"]
    market_snapshot_json: Dict[str, Any] = Field(default_factory=dict)
    decision_json: Dict[str, Any] = Field(default_factory=dict)
    outcome_json: Dict[str, Any] = Field(default_factory=dict)
    trade_ids: List[str] = Field(default_factory=list)


class AgentPerformance(DBModel):
    id: Optional[int] = None
    agent_id: int
    date: Optional[str] = None
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    sharpe_rolling_30d: float = 0.0
    max_drawdown: float = 0.0
    equity: float = 0.0


class Signal(DBModel):
    id: Optional[int] = None
    source: str = ""
    symbol: str = ""
    side: str = ""
    confidence: Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    status: str = "received"
    auto_executed: bool = False
    agent_id: Optional[int] = None
    raw_payload: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


class TradeAttribution(DBModel):
    """Links every fill back to the signal that generated it."""
    id: Optional[int] = None
    trade_id: str
    agent_id: int
    strategy_name: str
    signal_type: str = ""
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    hold_duration_seconds: Optional[int] = None
    market_regime: str = "unknown"
    params_snapshot: Dict[str, Any] = Field(default_factory=dict)
    entry_indicators: Dict[str, Any] = Field(default_factory=dict)
    exit_reason: Optional[str] = None
    closed: bool = False
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class StrategyScorecard(DBModel):
    """Per-strategy, per-signal-type performance metrics."""
    id: Optional[int] = None
    agent_id: int
    strategy_name: str
    signal_type: str = ""
    regime: str = "all"
    sample_size: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    avg_hold_duration: float = 0.0
    profit_factor: float = 0.0
    best_params: Dict[str, Any] = Field(default_factory=dict)
    worst_params: Dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None


class ParamMutation(DBModel):
    """Records every candidate parameter set tested and whether it was accepted."""
    id: Optional[int] = None
    agent_id: int
    previous_params: Dict[str, Any] = Field(default_factory=dict)
    candidate_params: Dict[str, Any] = Field(default_factory=dict)
    mutation_reason: str = ""
    backtest_sharpe: Optional[float] = None
    backtest_win_rate: Optional[float] = None
    backtest_pnl: Optional[float] = None
    backtest_trades: Optional[int] = None
    accepted: bool = False
    live_pnl_after_7d: Optional[float] = None
    created_at: Optional[datetime] = None


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

    async def create_strategy(self, strategy: Strategy) -> Optional[int]:
        raise NotImplementedError

    async def get_strategies(self) -> List[Strategy]:
        raise NotImplementedError

    async def get_strategy(self, strategy_id: int) -> Optional[Strategy]:
        raise NotImplementedError

    async def get_strategy_by_name(self, name: str) -> Optional[Strategy]:
        raise NotImplementedError

    async def update_strategy(self, strategy: Strategy) -> bool:
        raise NotImplementedError
    
    async def toggle_strategy_active(self, strategy_id: int, is_active: bool) -> bool:
        raise NotImplementedError


    async def create_trade(self, trade: Trade) -> Optional[int]:
        raise NotImplementedError

    async def create_order_intent(self, intent: OrderIntent) -> Optional[int]:
        raise NotImplementedError

    async def update_order_intent(self, intent: OrderIntent) -> bool:
        raise NotImplementedError

    async def get_order_intent(self, idempotency_key: str) -> Optional[OrderIntent]:
        raise NotImplementedError

    async def list_open_order_intents(self, mode: Mode, run_id: str) -> List[OrderIntent]:
        raise NotImplementedError

    async def create_order_intent_event(self, event: OrderIntentEvent) -> Optional[int]:
        raise NotImplementedError

    async def create_order_fill(self, fill: OrderFill) -> Optional[int]:
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

    async def get_trades_by_order_ids(
        self,
        order_ids: List[str],
        *,
        run_id: Optional[str] = None,
        mode: Optional[Mode] = None,
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

    async def get_pnl_history(self, days: int = 60) -> List[PnLEntry]:
        return []

    # -- Credentials CRUD --
    async def store_credential(
        self, *, exchange_id: str, label: str, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str], is_testnet: bool,
    ) -> Optional[int]:
        raise NotImplementedError

    async def get_credential(self, credential_id: int) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def list_credentials(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def delete_credential(self, credential_id: int) -> bool:
        raise NotImplementedError

    async def update_credential(
        self, *, credential_id: int, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str],
    ) -> bool:
        raise NotImplementedError

    # -- Backtest Jobs CRUD --
    async def create_backtest_job(
        self, *, job_id: str, symbol: str, start_date: str, end_date: str,
        strategy_id: Optional[int] = None,
    ) -> Optional[int]:
        raise NotImplementedError

    async def get_backtest_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def update_backtest_job(
        self, job_id: str, *, status: Optional[str] = None,
        result_json: Optional[dict] = None, error: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError

    async def list_backtest_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        raise NotImplementedError

    # -- Agent CRUD --
    async def create_agent(self, agent: Agent) -> Optional[int]:
        raise NotImplementedError

    async def get_agent(self, agent_id: int) -> Optional[Agent]:
        raise NotImplementedError

    async def get_agent_by_name(self, name: str) -> Optional[Agent]:
        raise NotImplementedError

    async def list_agents(self, status: Optional[str] = None) -> List[Agent]:
        raise NotImplementedError

    async def update_agent(self, agent: Agent) -> bool:
        raise NotImplementedError

    async def update_agent_status(self, agent_id: int, status: str, paused_at: Optional[datetime] = None, retired_at: Optional[datetime] = None) -> bool:
        raise NotImplementedError

    async def delete_agent(self, agent_id: int) -> bool:
        raise NotImplementedError

    # -- Agent Decisions CRUD --
    async def create_agent_decision(self, decision: AgentDecision) -> Optional[int]:
        raise NotImplementedError

    async def get_agent_decisions(self, agent_id: int, limit: int = 50) -> List[AgentDecision]:
        raise NotImplementedError

    # -- Agent Performance CRUD --
    async def upsert_agent_performance(self, perf: AgentPerformance) -> bool:
        raise NotImplementedError

    async def get_agent_performance(self, agent_id: int, days: int = 30) -> List[AgentPerformance]:
        raise NotImplementedError

    async def create_signal(self, signal: Signal) -> Optional[int]:
        raise NotImplementedError

    async def list_signals(self, limit: int = 50, source: Optional[str] = None) -> List[Signal]:
        raise NotImplementedError

    async def update_signal_status(self, signal_id: int, status: str, auto_executed: bool = False) -> bool:
        raise NotImplementedError

    # -- Trade Attribution CRUD --
    async def create_trade_attribution(self, attr: TradeAttribution) -> Optional[int]:
        raise NotImplementedError

    async def close_trade_attribution(
        self, trade_id: str, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        raise NotImplementedError

    async def close_oldest_open_attribution(
        self, agent_id: int, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        raise NotImplementedError

    async def get_trade_attributions(
        self, agent_id: int, limit: int = 100, closed_only: bool = False,
    ) -> List[TradeAttribution]:
        raise NotImplementedError

    # -- Strategy Scorecard CRUD --
    async def upsert_strategy_scorecard(self, sc: StrategyScorecard) -> bool:
        raise NotImplementedError

    async def get_strategy_scorecards(
        self, agent_id: int, strategy_name: Optional[str] = None,
    ) -> List[StrategyScorecard]:
        raise NotImplementedError

    # -- Param Mutation CRUD --
    async def create_param_mutation(self, mutation: ParamMutation) -> Optional[int]:
        raise NotImplementedError

    async def get_param_mutations(
        self, agent_id: int, limit: int = 50, accepted_only: bool = False,
    ) -> List[ParamMutation]:
        raise NotImplementedError

    async def get_successful_mutations(
        self, strategy_name: str, min_sharpe_improvement: float = 0.1, days: int = 14,
    ) -> List[ParamMutation]:
        raise NotImplementedError

    async def update_param_mutation_live_pnl(
        self, mutation_id: int, live_pnl: float,
    ) -> bool:
        raise NotImplementedError

    # -- Audit Log --
    async def log_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        actor: str = "system",
        ip: Optional[str] = None,
    ) -> Optional[int]:
        raise NotImplementedError


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

                CREATE TABLE IF NOT EXISTS order_intents (
                    id SERIAL PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    client_id TEXT UNIQUE NOT NULL,
                    order_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity DOUBLE PRECISION NOT NULL,
                    price DOUBLE PRECISION,
                    stop_price DOUBLE PRECISION,
                    reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
                    status TEXT NOT NULL,
                    filled_qty DOUBLE PRECISION NOT NULL DEFAULT 0,
                    avg_fill_price DOUBLE PRECISION,
                    last_error TEXT,
                    mode TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_order_intents_status ON order_intents(status);
                CREATE INDEX IF NOT EXISTS idx_order_intents_symbol ON order_intents(symbol);

                CREATE TABLE IF NOT EXISTS order_intent_events (
                    id SERIAL PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_order_intent_events_key ON order_intent_events(idempotency_key);

                CREATE TABLE IF NOT EXISTS order_fills (
                    id SERIAL PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    trade_id TEXT UNIQUE NOT NULL,
                    order_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity DOUBLE PRECISION NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    fee DOUBLE PRECISION NOT NULL DEFAULT 0,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS strategies (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    config JSONB NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pnl_entries (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    trade_id TEXT UNIQUE NOT NULL,
                    realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    commission DOUBLE PRECISION NOT NULL DEFAULT 0,
                    fees DOUBLE PRECISION NOT NULL DEFAULT 0,
                    funding DOUBLE PRECISION NOT NULL DEFAULT 0,
                    net_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    balance DOUBLE PRECISION NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_pnl_entries_timestamp ON pnl_entries(timestamp);
                CREATE INDEX IF NOT EXISTS idx_pnl_entries_mode_run ON pnl_entries(mode, run_id);

                CREATE TABLE IF NOT EXISTS credentials (
                    id SERIAL PRIMARY KEY,
                    exchange_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    api_key_enc TEXT NOT NULL,
                    api_secret_enc TEXT NOT NULL,
                    passphrase_enc TEXT,
                    is_testnet BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS backtest_jobs (
                    id SERIAL PRIMARY KEY,
                    job_id TEXT UNIQUE NOT NULL,
                    strategy_id INTEGER,
                    symbol TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    result_json JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS idx_backtest_jobs_status ON backtest_jobs(status);
                CREATE INDEX IF NOT EXISTS idx_backtest_jobs_job_id ON backtest_jobs(job_id);

                CREATE TABLE IF NOT EXISTS agents (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'created',
                    config_json JSONB NOT NULL DEFAULT '{}',
                    allocation_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    paused_at TIMESTAMPTZ,
                    retired_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

                CREATE TABLE IF NOT EXISTS agent_decisions (
                    id SERIAL PRIMARY KEY,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    phase TEXT NOT NULL,
                    market_snapshot_json JSONB NOT NULL DEFAULT '{}',
                    decision_json JSONB NOT NULL DEFAULT '{}',
                    outcome_json JSONB NOT NULL DEFAULT '{}',
                    trade_ids TEXT[] NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent ON agent_decisions(agent_id);
                CREATE INDEX IF NOT EXISTS idx_agent_decisions_ts ON agent_decisions(timestamp);

                CREATE TABLE IF NOT EXISTS agent_performance (
                    id SERIAL PRIMARY KEY,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    date DATE NOT NULL,
                    realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    total_trades INTEGER NOT NULL DEFAULT 0,
                    win_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                    sharpe_rolling_30d DOUBLE PRECISION NOT NULL DEFAULT 0,
                    max_drawdown DOUBLE PRECISION NOT NULL DEFAULT 0,
                    equity DOUBLE PRECISION NOT NULL DEFAULT 0,
                    UNIQUE(agent_id, date)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_performance_agent ON agent_performance(agent_id);

                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    confidence DOUBLE PRECISION,
                    entry_price DOUBLE PRECISION,
                    stop_loss DOUBLE PRECISION,
                    take_profit DOUBLE PRECISION,
                    status TEXT NOT NULL DEFAULT 'received',
                    auto_executed BOOLEAN NOT NULL DEFAULT FALSE,
                    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    raw_payload JSONB NOT NULL DEFAULT '{}',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
                CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);

                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    details_json TEXT,
                    ip_address TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);

                CREATE TABLE IF NOT EXISTS trade_attributions (
                    id SERIAL PRIMARY KEY,
                    trade_id TEXT UNIQUE NOT NULL,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    strategy_name TEXT NOT NULL,
                    signal_type TEXT NOT NULL DEFAULT '',
                    entry_price DOUBLE PRECISION NOT NULL DEFAULT 0,
                    exit_price DOUBLE PRECISION,
                    realized_pnl DOUBLE PRECISION,
                    hold_duration_seconds INTEGER,
                    market_regime TEXT NOT NULL DEFAULT 'unknown',
                    params_snapshot JSONB NOT NULL DEFAULT '{}',
                    entry_indicators JSONB NOT NULL DEFAULT '{}',
                    exit_reason TEXT,
                    closed BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS idx_trade_attr_agent ON trade_attributions(agent_id);
                CREATE INDEX IF NOT EXISTS idx_trade_attr_strategy ON trade_attributions(strategy_name);
                CREATE INDEX IF NOT EXISTS idx_trade_attr_closed ON trade_attributions(closed);

                CREATE TABLE IF NOT EXISTS strategy_scorecards (
                    id SERIAL PRIMARY KEY,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    strategy_name TEXT NOT NULL,
                    signal_type TEXT NOT NULL DEFAULT '',
                    regime TEXT NOT NULL DEFAULT 'all',
                    sample_size INTEGER NOT NULL DEFAULT 0,
                    win_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                    avg_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
                    avg_hold_duration DOUBLE PRECISION NOT NULL DEFAULT 0,
                    profit_factor DOUBLE PRECISION NOT NULL DEFAULT 0,
                    best_params JSONB NOT NULL DEFAULT '{}',
                    worst_params JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_id, strategy_name, signal_type, regime)
                );
                CREATE INDEX IF NOT EXISTS idx_scorecard_agent ON strategy_scorecards(agent_id);

                CREATE TABLE IF NOT EXISTS param_mutations (
                    id SERIAL PRIMARY KEY,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    previous_params JSONB NOT NULL DEFAULT '{}',
                    candidate_params JSONB NOT NULL DEFAULT '{}',
                    mutation_reason TEXT NOT NULL DEFAULT '',
                    backtest_sharpe DOUBLE PRECISION,
                    backtest_win_rate DOUBLE PRECISION,
                    backtest_pnl DOUBLE PRECISION,
                    backtest_trades INTEGER,
                    accepted BOOLEAN NOT NULL DEFAULT FALSE,
                    live_pnl_after_7d DOUBLE PRECISION,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_param_mutations_agent ON param_mutations(agent_id);
                CREATE INDEX IF NOT EXISTS idx_param_mutations_accepted ON param_mutations(accepted);
            """)

            # Migration: add strategy columns to agents if missing
            col_check = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'agents' AND column_name = 'strategy_name'"
            )
            if not col_check:
                await conn.execute("ALTER TABLE agents ADD COLUMN strategy_name TEXT")
                await conn.execute("ALTER TABLE agents ADD COLUMN strategy_params JSONB")

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

    async def create_order_intent(self, intent: OrderIntent) -> Optional[int]:
        if not self.pool:
            return None
        query = """
            INSERT INTO order_intents (
                idempotency_key, client_id, order_id, symbol, side, order_type,
                quantity, price, stop_price, reduce_only, status, filled_qty,
                avg_fill_price, last_error, mode, run_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT(idempotency_key) DO UPDATE SET
                order_id=excluded.order_id,
                quantity=excluded.quantity,
                price=excluded.price,
                stop_price=excluded.stop_price,
                reduce_only=excluded.reduce_only,
                status=excluded.status,
                filled_qty=excluded.filled_qty,
                avg_fill_price=excluded.avg_fill_price,
                last_error=excluded.last_error,
                updated_at=CURRENT_TIMESTAMP
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                intent.idempotency_key,
                intent.client_id,
                intent.order_id,
                intent.symbol,
                intent.side,
                intent.order_type,
                intent.quantity,
                intent.price,
                intent.stop_price,
                intent.reduce_only,
                intent.status,
                intent.filled_qty,
                intent.avg_fill_price,
                intent.last_error,
                intent.mode,
                intent.run_id,
            )

    async def update_order_intent(self, intent: OrderIntent) -> bool:
        if not self.pool:
            return False
        query = """
            UPDATE order_intents
            SET order_id = $1,
                status = $2,
                filled_qty = $3,
                avg_fill_price = $4,
                last_error = $5,
                updated_at = CURRENT_TIMESTAMP
            WHERE idempotency_key = $6
        """
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                query,
                intent.order_id,
                intent.status,
                intent.filled_qty,
                intent.avg_fill_price,
                intent.last_error,
                intent.idempotency_key,
            )
            return int(res.split(" ")[-1]) > 0

    async def get_order_intent(self, idempotency_key: str) -> Optional[OrderIntent]:
        if not self.pool:
            return None
        query = "SELECT * FROM order_intents WHERE idempotency_key = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, idempotency_key)
            return OrderIntent(**row) if row else None

    async def list_open_order_intents(self, mode: Mode, run_id: str) -> List[OrderIntent]:
        if not self.pool:
            return []
        query = """
            SELECT * FROM order_intents
            WHERE mode = $1 AND run_id = $2
            AND status NOT IN ('filled', 'canceled', 'failed')
            ORDER BY created_at DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, mode, run_id)
            return [OrderIntent(**row) for row in rows]

    async def create_order_intent_event(self, event: OrderIntentEvent) -> Optional[int]:
        if not self.pool:
            return None
        query = """
            INSERT INTO order_intent_events (idempotency_key, status, details)
            VALUES ($1, $2, $3)
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query, event.idempotency_key, event.status, event.details
            )

    async def create_order_fill(self, fill: OrderFill) -> Optional[int]:
        if not self.pool:
            return None
        query = """
            INSERT INTO order_fills (
                idempotency_key, trade_id, order_id, symbol, side, quantity, price, fee, timestamp
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT(trade_id) DO NOTHING
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                fill.idempotency_key,
                fill.trade_id,
                fill.order_id,
                fill.symbol,
                fill.side,
                fill.quantity,
                fill.price,
                fill.fee,
                fill.timestamp or datetime.now(timezone.utc),
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

    async def get_trades_by_order_ids(
        self,
        order_ids: List[str],
        *,
        run_id: Optional[str] = None,
        mode: Optional[Mode] = None,
        is_shadow: bool = False,
    ) -> List[Trade]:
        if not self.pool or not order_ids:
            return []
        table = "trades_shadow" if is_shadow else "trades"
        query = f"SELECT * FROM {table} WHERE order_id = ANY($1)"
        args: List[Any] = [order_ids]
        if run_id:
            args.append(run_id)
            query += f" AND run_id = ${len(args)}"
        if mode:
            args.append(mode)
            query += f" AND mode = ${len(args)}"
        query += " ORDER BY timestamp DESC"
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

    async def create_strategy(self, strategy: Strategy) -> Optional[int]:
        if not self.pool:
            return None
        import json
        query = """
            INSERT INTO strategies (name, config, is_active)
            VALUES ($1, $2, $3)
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                strategy.name,
                json.dumps(strategy.config), # Convert dict to JSON string for Postgres JSONB? Actually asyncpg handles dict to jsonb automatically if type is jsonb
                strategy.is_active
            )

    async def get_strategies(self) -> List[Strategy]:
        if not self.pool:
            return []
        import json
        query = "SELECT * FROM strategies ORDER BY created_at DESC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            # Asyncpg returns JSONB as string or dict depending on codec. Usually we need to parse if it comes back as string.
            # But asyncpg usually decodes JSON automatically. Let's assume it returns dict.
            # However Pydantic needs matched types.
            results = []
            for row in rows:
                r = dict(row)
                if isinstance(r['config'], str):
                     r['config'] = json.loads(r['config'])
                results.append(Strategy(**r))
            return results

    async def get_strategy(self, strategy_id: int) -> Optional[Strategy]:
        if not self.pool:
            return None
        import json
        query = "SELECT * FROM strategies WHERE id = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, strategy_id)
            if not row:
                return None
            r = dict(row)
            if isinstance(r['config'], str):
                r['config'] = json.loads(r['config'])
            return Strategy(**r)

    async def get_strategy_by_name(self, name: str) -> Optional[Strategy]:
        if not self.pool:
            return None
        import json
        query = "SELECT * FROM strategies WHERE name = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, name)
            if not row:
                return None
            r = dict(row)
            if isinstance(r['config'], str):
                r['config'] = json.loads(r['config'])
            return Strategy(**r)

    async def update_strategy(self, strategy: Strategy) -> bool:
        if not self.pool:
            return False
        import json
        query = """
            UPDATE strategies 
            SET name = $1, config = $2, is_active = $3, updated_at = CURRENT_TIMESTAMP
            WHERE id = $4
        """
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                query,
                strategy.name,
                json.dumps(strategy.config),
                strategy.is_active,
                strategy.id
            )
            return int(res.split(" ")[-1]) > 0
            
    async def toggle_strategy_active(self, strategy_id: int, is_active: bool) -> bool:
        if not self.pool:
            return False
        query = "UPDATE strategies SET is_active = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2"
        async with self.pool.acquire() as conn:
            res = await conn.execute(query, is_active, strategy_id)
            return int(res.split(" ")[-1]) > 0

    async def add_pnl_entry(self, entry: PnLEntry) -> bool:
        if not self.pool:
            return False
        query = """
            INSERT INTO pnl_entries (symbol, trade_id, realized_pnl, unrealized_pnl,
                commission, fees, funding, net_pnl, balance, mode, run_id, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT(trade_id) DO UPDATE SET
                realized_pnl=excluded.realized_pnl,
                unrealized_pnl=excluded.unrealized_pnl,
                commission=excluded.commission,
                fees=excluded.fees,
                funding=excluded.funding,
                net_pnl=excluded.net_pnl,
                balance=excluded.balance
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
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
                entry.timestamp or datetime.now(timezone.utc),
            )
            return True

    async def get_pnl_history(self, days: int = 60) -> List[PnLEntry]:
        if not self.pool:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
            SELECT * FROM pnl_entries
            WHERE timestamp >= $1
            ORDER BY timestamp DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, cutoff)
            return [PnLEntry(**dict(row)) for row in rows]

    async def aggregate_daily_pnl(self, days: int = 60) -> List[PnLEntry]:
        if not self.pool:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
            SELECT 
                DATE(timestamp) as day,
                mode,
                run_id,
                SUM(realized_pnl) as realized_pnl,
                SUM(unrealized_pnl) as unrealized_pnl,
                SUM(commission) as commission,
                SUM(fees) as fees,
                SUM(funding) as funding,
                SUM(net_pnl) as net_pnl,
                (SELECT balance FROM pnl_entries p2 
                 WHERE DATE(p2.timestamp) = DATE(pnl_entries.timestamp)
                 AND p2.mode = pnl_entries.mode 
                 AND p2.run_id = pnl_entries.run_id
                 ORDER BY p2.timestamp DESC LIMIT 1) as balance,
                MAX(timestamp) as timestamp
            FROM pnl_entries
            WHERE timestamp >= $1
            GROUP BY DATE(timestamp), mode, run_id
            ORDER BY day DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, cutoff)
            results = []
            for row in rows:
                d = dict(row)
                day_str = str(d.pop('day'))
                rollup_id = f"rollup-{d['mode']}-{d['run_id']}-{day_str}"
                results.append(PnLEntry(
                    symbol="ROLLUP",
                    trade_id=rollup_id,
                    realized_pnl=d['realized_pnl'] or 0.0,
                    unrealized_pnl=d['unrealized_pnl'] or 0.0,
                    commission=d['commission'] or 0.0,
                    fees=d['fees'] or 0.0,
                    funding=d['funding'] or 0.0,
                    net_pnl=d['net_pnl'] or 0.0,
                    balance=d['balance'] or 0.0,
                    mode=d['mode'],
                    run_id=d['run_id'],
                    timestamp=d['timestamp'],
                ))
            return results

    # -- Credentials CRUD (Postgres) --

    async def store_credential(
        self, *, exchange_id: str, label: str, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str], is_testnet: bool,
    ) -> Optional[int]:
        if not self.pool:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO credentials (exchange_id, label, api_key_enc, api_secret_enc, passphrase_enc, is_testnet)
                   VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                exchange_id, label, api_key_enc, api_secret_enc, passphrase_enc, is_testnet,
            )
            return row["id"] if row else None

    async def get_credential(self, credential_id: int) -> Optional[Dict[str, Any]]:
        if not self.pool:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM credentials WHERE id = $1", credential_id)
            if row:
                d = dict(row)
                d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else ""
                return d
            return None

    async def list_credentials(self) -> List[Dict[str, Any]]:
        if not self.pool:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, exchange_id, label, is_testnet, created_at FROM credentials ORDER BY created_at DESC"
            )
            results = []
            for row in rows:
                d = dict(row)
                d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else ""
                results.append(d)
            return results

    async def delete_credential(self, credential_id: int) -> bool:
        if not self.pool:
            return False
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM credentials WHERE id = $1", credential_id)
            return result == "DELETE 1"

    async def update_credential(
        self, *, credential_id: int, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str],
    ) -> bool:
        if not self.pool:
            return False
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE credentials SET api_key_enc = $1, api_secret_enc = $2, "
                "passphrase_enc = $3, updated_at = CURRENT_TIMESTAMP WHERE id = $4",
                api_key_enc, api_secret_enc, passphrase_enc, credential_id,
            )
            return result == "UPDATE 1"

    # -- Backtest Jobs CRUD (Postgres) --

    async def create_backtest_job(
        self, *, job_id: str, symbol: str, start_date: str, end_date: str,
        strategy_id: Optional[int] = None,
    ) -> Optional[int]:
        if not self.pool:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO backtest_jobs (job_id, strategy_id, symbol, start_date, end_date, status)
                   VALUES ($1, $2, $3, $4, $5, 'queued') RETURNING id""",
                job_id, strategy_id, symbol, start_date, end_date,
            )
            return row["id"] if row else None

    async def get_backtest_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        if not self.pool:
            return None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM backtest_jobs WHERE job_id = $1", job_id)
            if row:
                d = dict(row)
                for k in ("created_at", "completed_at"):
                    if d.get(k):
                        d[k] = d[k].isoformat()
                import json as _json
                if d.get("result_json") and isinstance(d["result_json"], str):
                    d["result_json"] = _json.loads(d["result_json"])
                return d
            return None

    async def update_backtest_job(
        self, job_id: str, *, status: Optional[str] = None,
        result_json: Optional[dict] = None, error: Optional[str] = None,
    ) -> bool:
        if not self.pool:
            return False
        import json as _json
        parts: list[str] = []
        args: list[Any] = []
        idx = 1
        if status is not None:
            parts.append(f"status = ${idx}")
            args.append(status)
            idx += 1
        if result_json is not None:
            parts.append(f"result_json = ${idx}")
            args.append(_json.dumps(result_json))
            idx += 1
        if error is not None:
            parts.append(f"error = ${idx}")
            args.append(error)
            idx += 1
        if status in ("completed", "failed"):
            parts.append("completed_at = CURRENT_TIMESTAMP")
        if not parts:
            return False
        args.append(job_id)
        query = f"UPDATE backtest_jobs SET {', '.join(parts)} WHERE job_id = ${idx}"
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *args)
            return "UPDATE 1" in result

    async def list_backtest_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.pool:
            return []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM backtest_jobs ORDER BY created_at DESC LIMIT $1", limit
            )
            results = []
            import json as _json
            for row in rows:
                d = dict(row)
                for k in ("created_at", "completed_at"):
                    if d.get(k):
                        d[k] = d[k].isoformat()
                if d.get("result_json") and isinstance(d["result_json"], str):
                    d["result_json"] = _json.loads(d["result_json"])
                results.append(d)
            return results

    # -- Agent CRUD (Postgres) --

    async def create_agent(self, agent: Agent) -> Optional[int]:
        if not self.pool:
            return None
        import json
        query = """
            INSERT INTO agents (name, status, config_json, allocation_usd, strategy_name, strategy_params)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                agent.name,
                agent.status,
                json.dumps(agent.config_json),
                agent.allocation_usd,
                agent.strategy_name,
                agent.strategy_params,
            )

    async def get_agent(self, agent_id: int) -> Optional[Agent]:
        if not self.pool:
            return None
        import json
        query = "SELECT * FROM agents WHERE id = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, agent_id)
            if not row:
                return None
            d = dict(row)
            if isinstance(d["config_json"], str):
                d["config_json"] = json.loads(d["config_json"])
            if isinstance(d.get("strategy_params"), str):
                d["strategy_params"] = d["strategy_params"]  # keep as JSON string
            return Agent(**d)

    async def get_agent_by_name(self, name: str) -> Optional[Agent]:
        if not self.pool:
            return None
        import json
        query = "SELECT * FROM agents WHERE name = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, name)
            if not row:
                return None
            d = dict(row)
            if isinstance(d["config_json"], str):
                d["config_json"] = json.loads(d["config_json"])
            return Agent(**d)

    async def list_agents(self, status: Optional[str] = None) -> List[Agent]:
        if not self.pool:
            return []
        import json
        query = "SELECT * FROM agents"
        args: list[Any] = []
        if status:
            query += " WHERE status = $1"
            args.append(status)
        query += " ORDER BY created_at DESC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d["config_json"], str):
                    d["config_json"] = json.loads(d["config_json"])
                results.append(Agent(**d))
            return results

    async def update_agent(self, agent: Agent) -> bool:
        if not self.pool:
            return False
        import json
        query = """
            UPDATE agents
            SET name = $1, status = $2, config_json = $3, allocation_usd = $4,
                strategy_name = $5, strategy_params = $6, updated_at = CURRENT_TIMESTAMP
            WHERE id = $7
        """
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                query,
                agent.name,
                agent.status,
                json.dumps(agent.config_json),
                agent.allocation_usd,
                agent.strategy_name,
                json.dumps(agent.strategy_params) if agent.strategy_params else None,
                agent.id,
            )
            return int(res.split(" ")[-1]) > 0

    async def update_agent_status(self, agent_id: int, status: str, paused_at: Optional[datetime] = None, retired_at: Optional[datetime] = None) -> bool:
        if not self.pool:
            return False
        query = """
            UPDATE agents
            SET status = $1, paused_at = $2, retired_at = $3, updated_at = CURRENT_TIMESTAMP
            WHERE id = $4
        """
        async with self.pool.acquire() as conn:
            res = await conn.execute(query, status, paused_at, retired_at, agent_id)
            return int(res.split(" ")[-1]) > 0

    async def delete_agent(self, agent_id: int) -> bool:
        if not self.pool:
            return False
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM agents WHERE id = $1", agent_id)
            return result == "DELETE 1"

    # -- Agent Decisions CRUD (Postgres) --

    async def create_agent_decision(self, decision: AgentDecision) -> Optional[int]:
        if not self.pool:
            return None
        import json
        query = """
            INSERT INTO agent_decisions (agent_id, timestamp, phase, market_snapshot_json, decision_json, outcome_json, trade_ids)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                decision.agent_id,
                decision.timestamp or datetime.now(timezone.utc),
                decision.phase,
                json.dumps(decision.market_snapshot_json),
                json.dumps(decision.decision_json),
                json.dumps(decision.outcome_json),
                decision.trade_ids,
            )

    async def get_agent_decisions(self, agent_id: int, limit: int = 50) -> List[AgentDecision]:
        if not self.pool:
            return []
        import json
        query = "SELECT * FROM agent_decisions WHERE agent_id = $1 ORDER BY timestamp DESC LIMIT $2"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, agent_id, limit)
            results = []
            for row in rows:
                d = dict(row)
                for k in ("market_snapshot_json", "decision_json", "outcome_json"):
                    if isinstance(d[k], str):
                        d[k] = json.loads(d[k])
                # trade_ids comes back as a list from asyncpg TEXT[]
                results.append(AgentDecision(**d))
            return results

    # -- Agent Performance CRUD (Postgres) --

    async def upsert_agent_performance(self, perf: AgentPerformance) -> bool:
        if not self.pool:
            return False
        query = """
            INSERT INTO agent_performance (agent_id, date, realized_pnl, unrealized_pnl, total_trades, win_rate, sharpe_rolling_30d, max_drawdown, equity)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT(agent_id, date) DO UPDATE SET
                realized_pnl=excluded.realized_pnl,
                unrealized_pnl=excluded.unrealized_pnl,
                total_trades=excluded.total_trades,
                win_rate=excluded.win_rate,
                sharpe_rolling_30d=excluded.sharpe_rolling_30d,
                max_drawdown=excluded.max_drawdown,
                equity=excluded.equity
        """
        perf_date = perf.date
        if isinstance(perf_date, str):
            from datetime import date as _date
            perf_date = _date.fromisoformat(perf_date)
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                perf.agent_id,
                perf_date,
                perf.realized_pnl,
                perf.unrealized_pnl,
                perf.total_trades,
                perf.win_rate,
                perf.sharpe_rolling_30d,
                perf.max_drawdown,
                perf.equity,
            )
            return True

    async def get_agent_performance(self, agent_id: int, days: int = 30) -> List[AgentPerformance]:
        if not self.pool:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()
        query = "SELECT * FROM agent_performance WHERE agent_id = $1 AND date >= $2 ORDER BY date DESC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, agent_id, cutoff)
            results = []
            for row in rows:
                d = dict(row)
                if d.get("date") and not isinstance(d["date"], str):
                    d["date"] = str(d["date"])
                results.append(AgentPerformance(**d))
            return results

    async def create_signal(self, signal: Signal) -> Optional[int]:
        if not self.pool:
            return None
        query = """
            INSERT INTO signals (source, symbol, side, confidence, entry_price, stop_loss, take_profit, status, auto_executed, agent_id, raw_payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
            RETURNING id
        """
        import json as _json
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                signal.source, signal.symbol, signal.side, signal.confidence,
                signal.entry_price, signal.stop_loss, signal.take_profit,
                signal.status, signal.auto_executed, signal.agent_id,
                _json.dumps(signal.raw_payload or {}),
            )

    async def list_signals(self, limit: int = 50, source: Optional[str] = None) -> List[Signal]:
        if not self.pool:
            return []
        if source:
            query = "SELECT * FROM signals WHERE source = $1 ORDER BY created_at DESC LIMIT $2"
            args = (source, limit)
        else:
            query = "SELECT * FROM signals ORDER BY created_at DESC LIMIT $1"
            args = (limit,)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            results = []
            for row in rows:
                d = dict(row)
                if d.get("created_at") and not isinstance(d["created_at"], str):
                    d["created_at"] = str(d["created_at"])
                results.append(Signal(**d))
            return results

    async def update_signal_status(self, signal_id: int, status: str, auto_executed: bool = False) -> bool:
        if not self.pool:
            return False
        query = "UPDATE signals SET status = $1, auto_executed = $2 WHERE id = $3"
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, status, auto_executed, signal_id)
            return "UPDATE 1" in result

    async def log_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        actor: str = "system",
        ip: Optional[str] = None,
    ) -> Optional[int]:
        if not self.pool:
            return None
        import json as _json
        query = """
            INSERT INTO audit_log (action, actor, resource_type, resource_id, details_json, ip_address)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval(
                    query, action, actor, resource_type, resource_id,
                    _json.dumps(details) if details else None, ip,
                )
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)
            return None

    # -- Trade Attribution CRUD (Postgres) --
    async def create_trade_attribution(self, attr: TradeAttribution) -> Optional[int]:
        if not self.pool:
            return None
        import json as _json
        query = """
            INSERT INTO trade_attributions (
                trade_id, agent_id, strategy_name, signal_type, entry_price,
                market_regime, params_snapshot, entry_indicators
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT(trade_id) DO UPDATE SET
                signal_type=excluded.signal_type, entry_price=excluded.entry_price,
                market_regime=excluded.market_regime, params_snapshot=excluded.params_snapshot,
                entry_indicators=excluded.entry_indicators
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query, attr.trade_id, attr.agent_id, attr.strategy_name,
                attr.signal_type, attr.entry_price, attr.market_regime,
                _json.dumps(attr.params_snapshot), _json.dumps(attr.entry_indicators),
            )

    async def close_trade_attribution(
        self, trade_id: str, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        if not self.pool:
            return False
        query = """
            UPDATE trade_attributions SET
                exit_price=$1, realized_pnl=$2, hold_duration_seconds=$3,
                exit_reason=$4, closed=TRUE, closed_at=CURRENT_TIMESTAMP
            WHERE trade_id=$5 AND closed=FALSE
        """
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                query, exit_price, realized_pnl, hold_duration_seconds,
                exit_reason, trade_id,
            )
            return int(res.split(" ")[-1]) > 0

    async def close_oldest_open_attribution(
        self, agent_id: int, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        if not self.pool:
            return False
        query = """
            UPDATE trade_attributions SET
                exit_price=$1, realized_pnl=$2, hold_duration_seconds=$3,
                exit_reason=$4, closed=TRUE, closed_at=CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM trade_attributions
                WHERE agent_id=$5 AND closed=FALSE
                ORDER BY created_at ASC
                LIMIT 1
            )
        """
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                query, exit_price, realized_pnl, hold_duration_seconds,
                exit_reason, agent_id,
            )
            return int(res.split(" ")[-1]) > 0

    async def get_trade_attributions(
        self, agent_id: int, limit: int = 100, closed_only: bool = False,
    ) -> List[TradeAttribution]:
        if not self.pool:
            return []
        import json as _json
        query = "SELECT * FROM trade_attributions WHERE agent_id = $1"
        if closed_only:
            query += " AND closed = TRUE"
        query += " ORDER BY created_at DESC LIMIT $2"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, agent_id, limit)
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("params_snapshot", "entry_indicators"):
                    if isinstance(d.get(jf), str):
                        d[jf] = _json.loads(d[jf])
                result.append(TradeAttribution(**d))
            return result

    # -- Strategy Scorecard CRUD (Postgres) --
    async def upsert_strategy_scorecard(self, sc: StrategyScorecard) -> bool:
        if not self.pool:
            return False
        import json as _json
        query = """
            INSERT INTO strategy_scorecards (
                agent_id, strategy_name, signal_type, regime,
                sample_size, win_rate, avg_pnl, avg_hold_duration,
                profit_factor, best_params, worst_params, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_id, strategy_name, signal_type, regime)
            DO UPDATE SET
                sample_size=excluded.sample_size, win_rate=excluded.win_rate,
                avg_pnl=excluded.avg_pnl, avg_hold_duration=excluded.avg_hold_duration,
                profit_factor=excluded.profit_factor,
                best_params=excluded.best_params, worst_params=excluded.worst_params,
                updated_at=CURRENT_TIMESTAMP
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            rid = await conn.fetchval(
                query, sc.agent_id, sc.strategy_name, sc.signal_type,
                sc.regime, sc.sample_size, sc.win_rate, sc.avg_pnl,
                sc.avg_hold_duration, sc.profit_factor,
                _json.dumps(sc.best_params), _json.dumps(sc.worst_params),
            )
            return rid is not None

    async def get_strategy_scorecards(
        self, agent_id: int, strategy_name: Optional[str] = None,
    ) -> List[StrategyScorecard]:
        if not self.pool:
            return []
        import json as _json
        query = "SELECT * FROM strategy_scorecards WHERE agent_id = $1"
        args: list = [agent_id]
        if strategy_name:
            args.append(strategy_name)
            query += f" AND strategy_name = ${len(args)}"
        query += " ORDER BY updated_at DESC"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("best_params", "worst_params"):
                    if isinstance(d.get(jf), str):
                        d[jf] = _json.loads(d[jf])
                result.append(StrategyScorecard(**d))
            return result

    # -- Param Mutation CRUD (Postgres) --
    async def create_param_mutation(self, mutation: ParamMutation) -> Optional[int]:
        if not self.pool:
            return None
        import json as _json
        query = """
            INSERT INTO param_mutations (
                agent_id, previous_params, candidate_params, mutation_reason,
                backtest_sharpe, backtest_win_rate, backtest_pnl,
                backtest_trades, accepted
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query, mutation.agent_id,
                _json.dumps(mutation.previous_params),
                _json.dumps(mutation.candidate_params),
                mutation.mutation_reason, mutation.backtest_sharpe,
                mutation.backtest_win_rate, mutation.backtest_pnl,
                mutation.backtest_trades, mutation.accepted,
            )

    async def get_param_mutations(
        self, agent_id: int, limit: int = 50, accepted_only: bool = False,
    ) -> List[ParamMutation]:
        if not self.pool:
            return []
        import json as _json
        query = "SELECT * FROM param_mutations WHERE agent_id = $1"
        if accepted_only:
            query += " AND accepted = TRUE"
        query += " ORDER BY created_at DESC LIMIT $2"
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, agent_id, limit)
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("previous_params", "candidate_params"):
                    if isinstance(d.get(jf), str):
                        d[jf] = _json.loads(d[jf])
                result.append(ParamMutation(**d))
            return result

    async def get_successful_mutations(
        self, strategy_name: str, min_sharpe_improvement: float = 0.1, days: int = 14,
    ) -> List[ParamMutation]:
        if not self.pool:
            return []
        import json as _json
        query = """
            SELECT pm.* FROM param_mutations pm
            JOIN agents a ON pm.agent_id = a.id
            WHERE a.strategy_name = $1
              AND pm.accepted = TRUE
              AND pm.backtest_sharpe >= $2
              AND pm.created_at >= CURRENT_TIMESTAMP - INTERVAL '1 day' * $3
            ORDER BY pm.backtest_sharpe DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, strategy_name, min_sharpe_improvement, days)
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("previous_params", "candidate_params"):
                    if isinstance(d.get(jf), str):
                        d[jf] = _json.loads(d[jf])
                result.append(ParamMutation(**d))
            return result

    async def update_param_mutation_live_pnl(
        self, mutation_id: int, live_pnl: float,
    ) -> bool:
        if not self.pool:
            return False
        query = "UPDATE param_mutations SET live_pnl_after_7d = $1 WHERE id = $2"
        async with self.pool.acquire() as conn:
            res = await conn.execute(query, live_pnl, mutation_id)
            return int(res.split(" ")[-1]) > 0


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

            CREATE TABLE IF NOT EXISTS order_intents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT UNIQUE NOT NULL,
                client_id TEXT UNIQUE NOT NULL,
                order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL,
                stop_price REAL,
                reduce_only INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                filled_qty REAL NOT NULL DEFAULT 0,
                avg_fill_price REAL,
                last_error TEXT,
                mode TEXT NOT NULL,
                run_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_order_intents_status ON order_intents(status);
            CREATE INDEX IF NOT EXISTS idx_order_intents_symbol ON order_intents(symbol);

            CREATE TABLE IF NOT EXISTS order_intent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_order_intent_events_key ON order_intent_events(idempotency_key);

            CREATE TABLE IF NOT EXISTS order_fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL,
                trade_id TEXT UNIQUE NOT NULL,
                order_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                config TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS pnl_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_id TEXT UNIQUE NOT NULL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                unrealized_pnl REAL NOT NULL DEFAULT 0,
                commission REAL NOT NULL DEFAULT 0,
                fees REAL NOT NULL DEFAULT 0,
                funding REAL NOT NULL DEFAULT 0,
                net_pnl REAL NOT NULL DEFAULT 0,
                balance REAL NOT NULL DEFAULT 0,
                mode TEXT NOT NULL,
                run_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_pnl_entries_timestamp ON pnl_entries(timestamp);
            CREATE INDEX IF NOT EXISTS idx_pnl_entries_mode_run ON pnl_entries(mode, run_id);

            CREATE TABLE IF NOT EXISTS credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange_id TEXT NOT NULL,
                label TEXT NOT NULL,
                api_key_enc TEXT NOT NULL,
                api_secret_enc TEXT NOT NULL,
                passphrase_enc TEXT,
                is_testnet INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS backtest_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                strategy_id INTEGER,
                symbol TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                result_json TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_backtest_jobs_status ON backtest_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_backtest_jobs_job_id ON backtest_jobs(job_id);

            CREATE TABLE IF NOT EXISTS agents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'created',
                config_json TEXT NOT NULL DEFAULT '{}',
                allocation_usd REAL NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paused_at TIMESTAMP,
                retired_at TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                phase TEXT NOT NULL,
                market_snapshot_json TEXT NOT NULL DEFAULT '{}',
                decision_json TEXT NOT NULL DEFAULT '{}',
                outcome_json TEXT NOT NULL DEFAULT '{}',
                trade_ids TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_agent_decisions_agent ON agent_decisions(agent_id);
            CREATE INDEX IF NOT EXISTS idx_agent_decisions_ts ON agent_decisions(timestamp);

            CREATE TABLE IF NOT EXISTS agent_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                date TEXT NOT NULL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                unrealized_pnl REAL NOT NULL DEFAULT 0,
                total_trades INTEGER NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0,
                sharpe_rolling_30d REAL NOT NULL DEFAULT 0,
                max_drawdown REAL NOT NULL DEFAULT 0,
                equity REAL NOT NULL DEFAULT 0,
                UNIQUE(agent_id, date)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_performance_agent ON agent_performance(agent_id);

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                action TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'system',
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                details_json TEXT,
                ip_address TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);

            CREATE TABLE IF NOT EXISTS trade_attributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE NOT NULL,
                agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                strategy_name TEXT NOT NULL,
                signal_type TEXT NOT NULL DEFAULT '',
                entry_price REAL NOT NULL DEFAULT 0,
                exit_price REAL,
                realized_pnl REAL,
                hold_duration_seconds INTEGER,
                market_regime TEXT NOT NULL DEFAULT 'unknown',
                params_snapshot TEXT NOT NULL DEFAULT '{}',
                entry_indicators TEXT NOT NULL DEFAULT '{}',
                exit_reason TEXT,
                closed INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_trade_attr_agent ON trade_attributions(agent_id);
            CREATE INDEX IF NOT EXISTS idx_trade_attr_strategy ON trade_attributions(strategy_name);
            CREATE INDEX IF NOT EXISTS idx_trade_attr_closed ON trade_attributions(closed);

            CREATE TABLE IF NOT EXISTS strategy_scorecards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                strategy_name TEXT NOT NULL,
                signal_type TEXT NOT NULL DEFAULT '',
                regime TEXT NOT NULL DEFAULT 'all',
                sample_size INTEGER NOT NULL DEFAULT 0,
                win_rate REAL NOT NULL DEFAULT 0,
                avg_pnl REAL NOT NULL DEFAULT 0,
                avg_hold_duration REAL NOT NULL DEFAULT 0,
                profit_factor REAL NOT NULL DEFAULT 0,
                best_params TEXT NOT NULL DEFAULT '{}',
                worst_params TEXT NOT NULL DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_id, strategy_name, signal_type, regime)
            );
            CREATE INDEX IF NOT EXISTS idx_scorecard_agent ON strategy_scorecards(agent_id);

            CREATE TABLE IF NOT EXISTS param_mutations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                previous_params TEXT NOT NULL DEFAULT '{}',
                candidate_params TEXT NOT NULL DEFAULT '{}',
                mutation_reason TEXT NOT NULL DEFAULT '',
                backtest_sharpe REAL,
                backtest_win_rate REAL,
                backtest_pnl REAL,
                backtest_trades INTEGER,
                accepted INTEGER NOT NULL DEFAULT 0,
                live_pnl_after_7d REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_param_mutations_agent ON param_mutations(agent_id);
            CREATE INDEX IF NOT EXISTS idx_param_mutations_accepted ON param_mutations(accepted);
        """)

        async with self.conn.execute("PRAGMA table_info(agents)") as cursor:
            cols = [row[1] for row in await cursor.fetchall()]
        if "strategy_name" not in cols:
            await self.conn.execute("ALTER TABLE agents ADD COLUMN strategy_name TEXT")
            await self.conn.execute("ALTER TABLE agents ADD COLUMN strategy_params TEXT")
            await self.conn.commit()

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

    async def get_trades_by_order_ids(
        self,
        order_ids: List[str],
        *,
        run_id: Optional[str] = None,
        mode: Optional[Mode] = None,
        is_shadow: bool = False,
    ) -> List[Trade]:
        if not self.conn or not order_ids:
            return []
        table = "trades_shadow" if is_shadow else "trades"
        placeholders = ", ".join(["?"] * len(order_ids))
        query = f"SELECT * FROM {table} WHERE order_id IN ({placeholders})"
        args: List[Any] = list(order_ids)
        if run_id:
            query += " AND run_id = ?"
            args.append(run_id)
        if mode:
            query += " AND mode = ?"
            args.append(mode)
        query += " ORDER BY timestamp DESC"
        _log_query(query, args)
        async with self.conn.execute(query, tuple(args)) as cursor:
            rows = await cursor.fetchall()
            return [Trade(**dict(row)) for row in rows]

    async def create_order_intent(self, intent: OrderIntent) -> Optional[int]:
        if not self.conn:
            return None
        query = """
            INSERT INTO order_intents (
                idempotency_key, client_id, order_id, symbol, side, order_type,
                quantity, price, stop_price, reduce_only, status, filled_qty,
                avg_fill_price, last_error, mode, run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET
                order_id=excluded.order_id,
                quantity=excluded.quantity,
                price=excluded.price,
                stop_price=excluded.stop_price,
                reduce_only=excluded.reduce_only,
                status=excluded.status,
                filled_qty=excluded.filled_qty,
                avg_fill_price=excluded.avg_fill_price,
                last_error=excluded.last_error,
                updated_at=CURRENT_TIMESTAMP
        """
        try:
            params = (
                intent.idempotency_key,
                intent.client_id,
                intent.order_id,
                intent.symbol,
                intent.side,
                intent.order_type,
                intent.quantity,
                intent.price,
                intent.stop_price,
                1 if intent.reduce_only else 0,
                intent.status,
                intent.filled_qty,
                intent.avg_fill_price,
                intent.last_error,
                intent.mode,
                intent.run_id,
            )
            cursor = await self.conn.execute(query, params)
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_order_intent failed: %s", e)
            return None

    async def update_order_intent(self, intent: OrderIntent) -> bool:
        if not self.conn:
            return False
        query = """
            UPDATE order_intents
            SET order_id = ?,
                status = ?,
                filled_qty = ?,
                avg_fill_price = ?,
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE idempotency_key = ?
        """
        cursor = await self.conn.execute(
            query,
            (
                intent.order_id,
                intent.status,
                intent.filled_qty,
                intent.avg_fill_price,
                intent.last_error,
                intent.idempotency_key,
            ),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_order_intent(self, idempotency_key: str) -> Optional[OrderIntent]:
        if not self.conn:
            return None
        query = "SELECT * FROM order_intents WHERE idempotency_key = ?"
        async with self.conn.execute(query, (idempotency_key,)) as cursor:
            row = await cursor.fetchone()
            return OrderIntent(**dict(row)) if row else None

    async def list_open_order_intents(self, mode: Mode, run_id: str) -> List[OrderIntent]:
        if not self.conn:
            return []
        query = """
            SELECT * FROM order_intents
            WHERE mode = ? AND run_id = ?
            AND status NOT IN ('filled', 'canceled', 'failed')
            ORDER BY created_at DESC
        """
        async with self.conn.execute(query, (mode, run_id)) as cursor:
            rows = await cursor.fetchall()
            return [OrderIntent(**dict(row)) for row in rows]

    async def create_order_intent_event(self, event: OrderIntentEvent) -> Optional[int]:
        if not self.conn:
            return None
        query = """
            INSERT INTO order_intent_events (idempotency_key, status, details)
            VALUES (?, ?, ?)
        """
        try:
            cursor = await self.conn.execute(
                query, (event.idempotency_key, event.status, event.details)
            )
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_order_intent_event failed: %s", e)
            return None

    async def create_order_fill(self, fill: OrderFill) -> Optional[int]:
        if not self.conn:
            return None
        query = """
            INSERT INTO order_fills (
                idempotency_key, trade_id, order_id, symbol, side, quantity, price, fee, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO NOTHING
        """
        try:
            cursor = await self.conn.execute(
                query,
                (
                    fill.idempotency_key,
                    fill.trade_id,
                    fill.order_id,
                    fill.symbol,
                    fill.side,
                    fill.quantity,
                    fill.price,
                    fill.fee,
                    fill.timestamp or datetime.now(timezone.utc),
                ),
            )
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_order_fill failed: %s", e)
            return None

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

    async def create_strategy(self, strategy: Strategy) -> Optional[int]:
        if not self.conn:
            return None
        import json
        query = """
            INSERT INTO strategies (name, config, is_active)
            VALUES (?, ?, ?)
        """
        try:
            cursor = await self.conn.execute(
                query, (strategy.name, json.dumps(strategy.config), 1 if strategy.is_active else 0)
            )
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_strategy failed: %s", e)
            return None

    async def get_strategies(self) -> List[Strategy]:
        if not self.conn:
            return []
        import json
        query = "SELECT * FROM strategies ORDER BY created_at DESC"
        async with self.conn.execute(query) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d['config'] = json.loads(d['config'])
                d['is_active'] = bool(d['is_active'])
                results.append(Strategy(**d))
            return results

    async def get_strategy(self, strategy_id: int) -> Optional[Strategy]:
        if not self.conn:
            return None
        import json
        query = "SELECT * FROM strategies WHERE id = ?"
        async with self.conn.execute(query, (strategy_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d['config'] = json.loads(d['config'])
            d['is_active'] = bool(d['is_active'])
            return Strategy(**d)

    async def get_strategy_by_name(self, name: str) -> Optional[Strategy]:
        if not self.conn:
            return None
        import json
        query = "SELECT * FROM strategies WHERE name = ?"
        async with self.conn.execute(query, (name,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d['config'] = json.loads(d['config'])
            d['is_active'] = bool(d['is_active'])
            return Strategy(**d)

    async def update_strategy(self, strategy: Strategy) -> bool:
        if not self.conn:
            return False
        import json
        query = """
            UPDATE strategies 
            SET name = ?, config = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """
        try:
            cursor = await self.conn.execute(
                query,
                (
                    strategy.name,
                    json.dumps(strategy.config),
                    1 if strategy.is_active else 0,
                    strategy.id
                )
            )
            await self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("SQLite update_strategy failed: %s", e)
            return False

    async def toggle_strategy_active(self, strategy_id: int, is_active: bool) -> bool:
        if not self.conn:
            return False
        query = "UPDATE strategies SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        try:
            cursor = await self.conn.execute(query, (1 if is_active else 0, strategy_id))
            await self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("SQLite toggle_strategy_active failed: %s", e)
            return False

    async def add_pnl_entry(self, entry: PnLEntry) -> bool:
        if not self.conn:
            return False
        query = """
            INSERT INTO pnl_entries (symbol, trade_id, realized_pnl, unrealized_pnl,
                commission, fees, funding, net_pnl, balance, mode, run_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO UPDATE SET
                realized_pnl=excluded.realized_pnl,
                unrealized_pnl=excluded.unrealized_pnl,
                commission=excluded.commission,
                fees=excluded.fees,
                funding=excluded.funding,
                net_pnl=excluded.net_pnl,
                balance=excluded.balance
        """
        try:
            await self.conn.execute(
                query,
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
                    entry.timestamp or datetime.now(timezone.utc),
                ),
            )
            await self.conn.commit()
            return True
        except Exception as e:
            logger.error("SQLite add_pnl_entry failed: %s", e)
            return False

    async def get_pnl_history(self, days: int = 60) -> List[PnLEntry]:
        if not self.conn:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = """
            SELECT * FROM pnl_entries
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
        """
        try:
            async with self.conn.execute(query, (cutoff.isoformat(),)) as cursor:
                rows = await cursor.fetchall()
                return [PnLEntry(**dict(row)) for row in rows]
        except Exception as e:
            logger.error("SQLite get_pnl_history failed: %s", e)
            return []

    async def aggregate_daily_pnl(self, days: int = 60) -> List[PnLEntry]:
        if not self.conn:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        # Group by date, mode, run_id and aggregate
        query = """
            SELECT 
                DATE(timestamp) as day,
                mode,
                run_id,
                SUM(realized_pnl) as realized_pnl,
                SUM(unrealized_pnl) as unrealized_pnl,
                SUM(commission) as commission,
                SUM(fees) as fees,
                SUM(funding) as funding,
                SUM(net_pnl) as net_pnl,
                (SELECT balance FROM pnl_entries p2 
                 WHERE DATE(p2.timestamp) = DATE(pnl_entries.timestamp)
                 AND p2.mode = pnl_entries.mode 
                 AND p2.run_id = pnl_entries.run_id
                 ORDER BY p2.timestamp DESC LIMIT 1) as balance,
                MAX(timestamp) as timestamp
            FROM pnl_entries
            WHERE timestamp >= ?
            GROUP BY DATE(timestamp), mode, run_id
            ORDER BY day DESC
        """
        try:
            async with self.conn.execute(query, (cutoff.isoformat(),)) as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    d = dict(row)
                    day_str = d.pop('day')
                    # Create rollup trade_id
                    rollup_id = f"rollup-{d['mode']}-{d['run_id']}-{day_str}"
                    results.append(PnLEntry(
                        symbol="ROLLUP",
                        trade_id=rollup_id,
                        realized_pnl=d['realized_pnl'] or 0.0,
                        unrealized_pnl=d['unrealized_pnl'] or 0.0,
                        commission=d['commission'] or 0.0,
                        fees=d['fees'] or 0.0,
                        funding=d['funding'] or 0.0,
                        net_pnl=d['net_pnl'] or 0.0,
                        balance=d['balance'] or 0.0,
                        mode=d['mode'],
                        run_id=d['run_id'],
                        timestamp=d['timestamp'],
                    ))
                return results
        except Exception as e:
            logger.error("SQLite aggregate_daily_pnl failed: %s", e)
            return []

    # -- Credentials CRUD (SQLite) --

    async def store_credential(
        self, *, exchange_id: str, label: str, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str], is_testnet: bool,
    ) -> Optional[int]:
        if not self.conn:
            return None
        cursor = await self.conn.execute(
            """INSERT INTO credentials (exchange_id, label, api_key_enc, api_secret_enc, passphrase_enc, is_testnet)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (exchange_id, label, api_key_enc, api_secret_enc, passphrase_enc, int(is_testnet)),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_credential(self, credential_id: int) -> Optional[Dict[str, Any]]:
        if not self.conn:
            return None
        cursor = await self.conn.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,))
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            d["is_testnet"] = bool(d.get("is_testnet", 0))
            d["created_at"] = str(d.get("created_at", ""))
            return d
        return None

    async def list_credentials(self) -> List[Dict[str, Any]]:
        if not self.conn:
            return []
        cursor = await self.conn.execute(
            "SELECT id, exchange_id, label, is_testnet, created_at FROM credentials ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["is_testnet"] = bool(d.get("is_testnet", 0))
            d["created_at"] = str(d.get("created_at", ""))
            results.append(d)
        return results

    async def delete_credential(self, credential_id: int) -> bool:
        if not self.conn:
            return False
        cursor = await self.conn.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))
        await self.conn.commit()
        return cursor.rowcount > 0

    async def update_credential(
        self, *, credential_id: int, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str],
    ) -> bool:
        if not self.conn:
            return False
        cursor = await self.conn.execute(
            "UPDATE credentials SET api_key_enc = ?, api_secret_enc = ?, "
            "passphrase_enc = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (api_key_enc, api_secret_enc, passphrase_enc, credential_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    # -- Backtest Jobs CRUD (SQLite) --

    async def create_backtest_job(
        self, *, job_id: str, symbol: str, start_date: str, end_date: str,
        strategy_id: Optional[int] = None,
    ) -> Optional[int]:
        if not self.conn:
            return None
        cursor = await self.conn.execute(
            """INSERT INTO backtest_jobs (job_id, strategy_id, symbol, start_date, end_date, status)
               VALUES (?, ?, ?, ?, ?, 'queued')""",
            (job_id, strategy_id, symbol, start_date, end_date),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_backtest_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        if not self.conn:
            return None
        cursor = await self.conn.execute("SELECT * FROM backtest_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            import json as _json
            if d.get("result_json") and isinstance(d["result_json"], str):
                try:
                    d["result_json"] = _json.loads(d["result_json"])
                except _json.JSONDecodeError:
                    pass
            return d
        return None

    async def update_backtest_job(
        self, job_id: str, *, status: Optional[str] = None,
        result_json: Optional[dict] = None, error: Optional[str] = None,
    ) -> bool:
        if not self.conn:
            return False
        import json as _json
        parts: list[str] = []
        args: list[Any] = []
        if status is not None:
            parts.append("status = ?")
            args.append(status)
        if result_json is not None:
            parts.append("result_json = ?")
            args.append(_json.dumps(result_json))
        if error is not None:
            parts.append("error = ?")
            args.append(error)
        if status in ("completed", "failed"):
            parts.append("completed_at = CURRENT_TIMESTAMP")
        if not parts:
            return False
        args.append(job_id)
        query = f"UPDATE backtest_jobs SET {', '.join(parts)} WHERE job_id = ?"
        cursor = await self.conn.execute(query, args)
        await self.conn.commit()
        return cursor.rowcount > 0

    async def list_backtest_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.conn:
            return []
        cursor = await self.conn.execute(
            "SELECT * FROM backtest_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        results = []
        import json as _json
        for row in rows:
            d = dict(row)
            if d.get("result_json") and isinstance(d["result_json"], str):
                try:
                    d["result_json"] = _json.loads(d["result_json"])
                except _json.JSONDecodeError:
                    pass
            results.append(d)
        return results

    # -- Agent CRUD (SQLite) --

    async def create_agent(self, agent: Agent) -> Optional[int]:
        if not self.conn:
            return None
        import json
        query = """
            INSERT INTO agents (name, status, config_json, allocation_usd, strategy_name, strategy_params)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        try:
            cursor = await self.conn.execute(
                query, (
                    agent.name,
                    agent.status,
                    json.dumps(agent.config_json),
                    agent.allocation_usd,
                    agent.strategy_name,
                    agent.strategy_params,
                )
            )
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_agent failed: %s", e)
            return None

    async def get_agent(self, agent_id: int) -> Optional[Agent]:
        if not self.conn:
            return None
        import json
        query = "SELECT * FROM agents WHERE id = ?"
        async with self.conn.execute(query, (agent_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["config_json"] = json.loads(d["config_json"])
            return Agent(**d)

    async def get_agent_by_name(self, name: str) -> Optional[Agent]:
        if not self.conn:
            return None
        import json
        query = "SELECT * FROM agents WHERE name = ?"
        async with self.conn.execute(query, (name,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            d = dict(row)
            d["config_json"] = json.loads(d["config_json"])
            return Agent(**d)

    async def list_agents(self, status: Optional[str] = None) -> List[Agent]:
        if not self.conn:
            return []
        import json
        query = "SELECT * FROM agents"
        args: list[Any] = []
        if status:
            query += " WHERE status = ?"
            args.append(status)
        query += " ORDER BY created_at DESC"
        async with self.conn.execute(query, tuple(args)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["config_json"] = json.loads(d["config_json"])
                results.append(Agent(**d))
            return results

    async def update_agent(self, agent: Agent) -> bool:
        if not self.conn:
            return False
        import json
        query = """
            UPDATE agents
            SET name = ?, status = ?, config_json = ?, allocation_usd = ?,
                strategy_name = ?, strategy_params = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """
        try:
            cursor = await self.conn.execute(
                query,
                (
                    agent.name,
                    agent.status,
                    json.dumps(agent.config_json),
                    agent.allocation_usd,
                    agent.strategy_name,
                    agent.strategy_params,
                    agent.id,
                ),
            )
            await self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("SQLite update_agent failed: %s", e)
            return False

    async def update_agent_status(self, agent_id: int, status: str, paused_at: Optional[datetime] = None, retired_at: Optional[datetime] = None) -> bool:
        if not self.conn:
            return False
        query = """
            UPDATE agents
            SET status = ?, paused_at = ?, retired_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """
        try:
            cursor = await self.conn.execute(query, (status, paused_at, retired_at, agent_id))
            await self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("SQLite update_agent_status failed: %s", e)
            return False

    async def delete_agent(self, agent_id: int) -> bool:
        if not self.conn:
            return False
        cursor = await self.conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await self.conn.commit()
        return cursor.rowcount > 0

    # -- Agent Decisions CRUD (SQLite) --

    async def create_agent_decision(self, decision: AgentDecision) -> Optional[int]:
        if not self.conn:
            return None
        import json
        query = """
            INSERT INTO agent_decisions (agent_id, timestamp, phase, market_snapshot_json, decision_json, outcome_json, trade_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        try:
            cursor = await self.conn.execute(
                query,
                (
                    decision.agent_id,
                    decision.timestamp or datetime.now(timezone.utc),
                    decision.phase,
                    json.dumps(decision.market_snapshot_json),
                    json.dumps(decision.decision_json),
                    json.dumps(decision.outcome_json),
                    json.dumps(decision.trade_ids),
                ),
            )
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("SQLite create_agent_decision failed: %s", e)
            return None

    async def get_agent_decisions(self, agent_id: int, limit: int = 50) -> List[AgentDecision]:
        if not self.conn:
            return []
        import json
        query = "SELECT * FROM agent_decisions WHERE agent_id = ? ORDER BY timestamp DESC LIMIT ?"
        async with self.conn.execute(query, (agent_id, limit)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                for k in ("market_snapshot_json", "decision_json", "outcome_json"):
                    d[k] = json.loads(d[k])
                d["trade_ids"] = json.loads(d["trade_ids"])
                results.append(AgentDecision(**d))
            return results

    # -- Agent Performance CRUD (SQLite) --

    async def upsert_agent_performance(self, perf: AgentPerformance) -> bool:
        if not self.conn:
            return False
        query = """
            INSERT INTO agent_performance (agent_id, date, realized_pnl, unrealized_pnl, total_trades, win_rate, sharpe_rolling_30d, max_drawdown, equity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, date) DO UPDATE SET
                realized_pnl=excluded.realized_pnl,
                unrealized_pnl=excluded.unrealized_pnl,
                total_trades=excluded.total_trades,
                win_rate=excluded.win_rate,
                sharpe_rolling_30d=excluded.sharpe_rolling_30d,
                max_drawdown=excluded.max_drawdown,
                equity=excluded.equity
        """
        try:
            await self.conn.execute(
                query,
                (
                    perf.agent_id,
                    perf.date,
                    perf.realized_pnl,
                    perf.unrealized_pnl,
                    perf.total_trades,
                    perf.win_rate,
                    perf.sharpe_rolling_30d,
                    perf.max_drawdown,
                    perf.equity,
                ),
            )
            await self.conn.commit()
            return True
        except Exception as e:
            logger.error("SQLite upsert_agent_performance failed: %s", e)
            return False

    async def get_agent_performance(self, agent_id: int, days: int = 30) -> List[AgentPerformance]:
        if not self.conn:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        query = "SELECT * FROM agent_performance WHERE agent_id = ? AND date >= ? ORDER BY date DESC"
        async with self.conn.execute(query, (agent_id, cutoff)) as cursor:
            rows = await cursor.fetchall()
            return [AgentPerformance(**dict(row)) for row in rows]

    async def log_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        actor: str = "system",
        ip: Optional[str] = None,
    ) -> Optional[int]:
        if not self.conn:
            return None
        import json as _json
        query = """
            INSERT INTO audit_log (action, actor, resource_type, resource_id, details_json, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        try:
            cursor = await self.conn.execute(
                query,
                (action, actor, resource_type, resource_id,
                 _json.dumps(details) if details else None, ip),
            )
            await self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)
            return None

    # -- Trade Attribution CRUD (SQLite) --
    async def create_trade_attribution(self, attr: TradeAttribution) -> Optional[int]:
        if not self.conn:
            return None
        import json as _json
        query = """
            INSERT INTO trade_attributions (
                trade_id, agent_id, strategy_name, signal_type, entry_price,
                market_regime, params_snapshot, entry_indicators
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO UPDATE SET
                signal_type=excluded.signal_type, entry_price=excluded.entry_price,
                market_regime=excluded.market_regime, params_snapshot=excluded.params_snapshot,
                entry_indicators=excluded.entry_indicators
        """
        cursor = await self.conn.execute(
            query,
            (attr.trade_id, attr.agent_id, attr.strategy_name,
             attr.signal_type, attr.entry_price, attr.market_regime,
             _json.dumps(attr.params_snapshot), _json.dumps(attr.entry_indicators)),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def close_trade_attribution(
        self, trade_id: str, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        if not self.conn:
            return False
        query = """
            UPDATE trade_attributions SET
                exit_price=?, realized_pnl=?, hold_duration_seconds=?,
                exit_reason=?, closed=1, closed_at=CURRENT_TIMESTAMP
            WHERE trade_id=? AND closed=0
        """
        cursor = await self.conn.execute(
            query, (exit_price, realized_pnl, hold_duration_seconds,
                    exit_reason, trade_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def close_oldest_open_attribution(
        self, agent_id: int, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        if not self.conn:
            return False
        query = """
            UPDATE trade_attributions SET
                exit_price=?, realized_pnl=?, hold_duration_seconds=?,
                exit_reason=?, closed=1, closed_at=CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM trade_attributions
                WHERE agent_id=? AND closed=0
                ORDER BY created_at ASC
                LIMIT 1
            )
        """
        cursor = await self.conn.execute(
            query, (exit_price, realized_pnl, hold_duration_seconds,
                    exit_reason, agent_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_trade_attributions(
        self, agent_id: int, limit: int = 100, closed_only: bool = False,
    ) -> List[TradeAttribution]:
        if not self.conn:
            return []
        import json as _json
        query = "SELECT * FROM trade_attributions WHERE agent_id = ?"
        if closed_only:
            query += " AND closed = 1"
        query += " ORDER BY created_at DESC LIMIT ?"
        async with self.conn.execute(query, (agent_id, limit)) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("params_snapshot", "entry_indicators"):
                    if isinstance(d.get(jf), str):
                        try:
                            d[jf] = _json.loads(d[jf])
                        except (ValueError, TypeError):
                            d[jf] = {}
                d["closed"] = bool(d.get("closed", 0))
                result.append(TradeAttribution(**d))
            return result

    # -- Strategy Scorecard CRUD (SQLite) --
    async def upsert_strategy_scorecard(self, sc: StrategyScorecard) -> bool:
        if not self.conn:
            return False
        import json as _json
        query = """
            INSERT INTO strategy_scorecards (
                agent_id, strategy_name, signal_type, regime,
                sample_size, win_rate, avg_pnl, avg_hold_duration,
                profit_factor, best_params, worst_params, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(agent_id, strategy_name, signal_type, regime)
            DO UPDATE SET
                sample_size=excluded.sample_size, win_rate=excluded.win_rate,
                avg_pnl=excluded.avg_pnl, avg_hold_duration=excluded.avg_hold_duration,
                profit_factor=excluded.profit_factor,
                best_params=excluded.best_params, worst_params=excluded.worst_params,
                updated_at=CURRENT_TIMESTAMP
        """
        cursor = await self.conn.execute(
            query,
            (sc.agent_id, sc.strategy_name, sc.signal_type,
             sc.regime, sc.sample_size, sc.win_rate, sc.avg_pnl,
             sc.avg_hold_duration, sc.profit_factor,
             _json.dumps(sc.best_params), _json.dumps(sc.worst_params)),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_strategy_scorecards(
        self, agent_id: int, strategy_name: Optional[str] = None,
    ) -> List[StrategyScorecard]:
        if not self.conn:
            return []
        import json as _json
        query = "SELECT * FROM strategy_scorecards WHERE agent_id = ?"
        args: list = [agent_id]
        if strategy_name:
            args.append(strategy_name)
            query += " AND strategy_name = ?"
        query += " ORDER BY updated_at DESC"
        async with self.conn.execute(query, args) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("best_params", "worst_params"):
                    if isinstance(d.get(jf), str):
                        try:
                            d[jf] = _json.loads(d[jf])
                        except (ValueError, TypeError):
                            d[jf] = {}
                result.append(StrategyScorecard(**d))
            return result

    # -- Param Mutation CRUD (SQLite) --
    async def create_param_mutation(self, mutation: ParamMutation) -> Optional[int]:
        if not self.conn:
            return None
        import json as _json
        query = """
            INSERT INTO param_mutations (
                agent_id, previous_params, candidate_params, mutation_reason,
                backtest_sharpe, backtest_win_rate, backtest_pnl,
                backtest_trades, accepted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = await self.conn.execute(
            query,
            (mutation.agent_id,
             _json.dumps(mutation.previous_params),
             _json.dumps(mutation.candidate_params),
             mutation.mutation_reason, mutation.backtest_sharpe,
             mutation.backtest_win_rate, mutation.backtest_pnl,
             mutation.backtest_trades, int(mutation.accepted)),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_param_mutations(
        self, agent_id: int, limit: int = 50, accepted_only: bool = False,
    ) -> List[ParamMutation]:
        if not self.conn:
            return []
        import json as _json
        query = "SELECT * FROM param_mutations WHERE agent_id = ?"
        if accepted_only:
            query += " AND accepted = 1"
        query += " ORDER BY created_at DESC LIMIT ?"
        async with self.conn.execute(query, (agent_id, limit)) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("previous_params", "candidate_params"):
                    if isinstance(d.get(jf), str):
                        try:
                            d[jf] = _json.loads(d[jf])
                        except (ValueError, TypeError):
                            d[jf] = {}
                d["accepted"] = bool(d.get("accepted", 0))
                result.append(ParamMutation(**d))
            return result

    async def get_successful_mutations(
        self, strategy_name: str, min_sharpe_improvement: float = 0.1, days: int = 14,
    ) -> List[ParamMutation]:
        if not self.conn:
            return []
        import json as _json
        query = """
            SELECT pm.* FROM param_mutations pm
            JOIN agents a ON pm.agent_id = a.id
            WHERE a.strategy_name = ?
              AND pm.accepted = 1
              AND pm.backtest_sharpe >= ?
              AND pm.created_at >= datetime('now', '-' || ? || ' days')
            ORDER BY pm.backtest_sharpe DESC
        """
        async with self.conn.execute(query, (strategy_name, min_sharpe_improvement, days)) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for jf in ("previous_params", "candidate_params"):
                    if isinstance(d.get(jf), str):
                        try:
                            d[jf] = _json.loads(d[jf])
                        except (ValueError, TypeError):
                            d[jf] = {}
                d["accepted"] = bool(d.get("accepted", 0))
                result.append(ParamMutation(**d))
            return result

    async def update_param_mutation_live_pnl(
        self, mutation_id: int, live_pnl: float,
    ) -> bool:
        if not self.conn:
            return False
        query = "UPDATE param_mutations SET live_pnl_after_7d = ? WHERE id = ?"
        cursor = await self.conn.execute(query, (live_pnl, mutation_id))
        await self.conn.commit()
        return cursor.rowcount > 0


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

    async def get_trades_by_order_ids(
        self,
        order_ids: List[str],
        *,
        run_id: Optional[str] = None,
        mode: Optional[Mode] = None,
        is_shadow: bool = False,
    ) -> List[Trade]:
        if self.backend:
            return await self.backend.get_trades_by_order_ids(
                order_ids, run_id=run_id, mode=mode, is_shadow=is_shadow
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

    async def create_strategy(self, strategy: Strategy) -> Optional[int]:
        if self.backend:
            return await self.backend.create_strategy(strategy)
        return None

    async def get_strategies(self) -> List[Strategy]:
        if self.backend:
            return await self.backend.get_strategies()
        return []

    async def get_strategy(self, strategy_id: int) -> Optional[Strategy]:
        if self.backend:
            return await self.backend.get_strategy(strategy_id)
        return None

    async def get_strategy_by_name(self, name: str) -> Optional[Strategy]:
        if self.backend:
            return await self.backend.get_strategy_by_name(name)
        return None

    async def update_strategy(self, strategy: Strategy) -> bool:
        if self.backend:
            return await self.backend.update_strategy(strategy)
        return False
        
    async def toggle_strategy_active(self, strategy_id: int, is_active: bool) -> bool:
        if self.backend:
            return await self.backend.toggle_strategy_active(strategy_id, is_active)
        return False

    async def aggregate_daily_pnl(self, days: int = 60) -> List[PnLEntry]:
        if self.backend:
            return await self.backend.aggregate_daily_pnl(days)
        return []

    async def add_pnl_entry(self, entry: PnLEntry) -> bool:
        if self.backend:
            return await self.backend.add_pnl_entry(entry)
        return True

    async def get_pnl_history(self, days: int = 60) -> List[PnLEntry]:
        if self.backend:
            return await self.backend.get_pnl_history(days)
        return []

    async def create_order_intent(self, intent: OrderIntent) -> Optional[int]:
        if self.backend:
            return await self.backend.create_order_intent(intent)
        return None

    async def update_order_intent(self, intent: OrderIntent) -> bool:
        if self.backend:
            return await self.backend.update_order_intent(intent)
        return False

    async def get_order_intent(self, idempotency_key: str) -> Optional[OrderIntent]:
        if self.backend:
            return await self.backend.get_order_intent(idempotency_key)
        return None

    async def list_open_order_intents(self, mode: Mode, run_id: str) -> List[OrderIntent]:
        if self.backend:
            return await self.backend.list_open_order_intents(mode, run_id)
        return []

    async def create_order_intent_event(self, event: OrderIntentEvent) -> Optional[int]:
        if self.backend:
            return await self.backend.create_order_intent_event(event)
        return None

    async def create_order_fill(self, fill: OrderFill) -> Optional[int]:
        if self.backend:
            return await self.backend.create_order_fill(fill)
        return None

    # -- Credentials CRUD (Facade) --

    async def store_credential(
        self, *, exchange_id: str, label: str, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str], is_testnet: bool,
    ) -> Optional[int]:
        if self.backend:
            return await self.backend.store_credential(
                exchange_id=exchange_id, label=label,
                api_key_enc=api_key_enc, api_secret_enc=api_secret_enc,
                passphrase_enc=passphrase_enc, is_testnet=is_testnet,
            )
        return None

    async def get_credential(self, credential_id: int) -> Optional[Dict[str, Any]]:
        if self.backend:
            return await self.backend.get_credential(credential_id)
        return None

    async def list_credentials(self) -> List[Dict[str, Any]]:
        if self.backend:
            return await self.backend.list_credentials()
        return []

    async def delete_credential(self, credential_id: int) -> bool:
        if self.backend:
            return await self.backend.delete_credential(credential_id)
        return False

    async def update_credential(
        self, *, credential_id: int, api_key_enc: str,
        api_secret_enc: str, passphrase_enc: Optional[str],
    ) -> bool:
        if self.backend:
            return await self.backend.update_credential(
                credential_id=credential_id,
                api_key_enc=api_key_enc,
                api_secret_enc=api_secret_enc,
                passphrase_enc=passphrase_enc,
            )
        return False

    # -- Backtest Jobs CRUD (Facade) --

    async def create_backtest_job(
        self, *, job_id: str, symbol: str, start_date: str, end_date: str,
        strategy_id: Optional[int] = None,
    ) -> Optional[int]:
        if self.backend:
            return await self.backend.create_backtest_job(
                job_id=job_id, symbol=symbol,
                start_date=start_date, end_date=end_date,
                strategy_id=strategy_id,
            )
        return None

    async def get_backtest_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        if self.backend:
            return await self.backend.get_backtest_job(job_id)
        return None

    async def update_backtest_job(
        self, job_id: str, *, status: Optional[str] = None,
        result_json: Optional[dict] = None, error: Optional[str] = None,
    ) -> bool:
        if self.backend:
            return await self.backend.update_backtest_job(
                job_id, status=status, result_json=result_json, error=error,
            )
        return False

    async def list_backtest_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self.backend:
            return await self.backend.list_backtest_jobs(limit)
        return []

    # -- Agent CRUD (Facade) --

    async def create_agent(self, agent: Agent) -> Optional[int]:
        if self.backend:
            return await self.backend.create_agent(agent)
        return None

    async def get_agent(self, agent_id: int) -> Optional[Agent]:
        if self.backend:
            return await self.backend.get_agent(agent_id)
        return None

    async def get_agent_by_name(self, name: str) -> Optional[Agent]:
        if self.backend:
            return await self.backend.get_agent_by_name(name)
        return None

    async def list_agents(self, status: Optional[str] = None) -> List[Agent]:
        if self.backend:
            return await self.backend.list_agents(status)
        return []

    async def update_agent(self, agent: Agent) -> bool:
        if self.backend:
            return await self.backend.update_agent(agent)
        return False

    async def update_agent_status(self, agent_id: int, status: str, paused_at: Optional[datetime] = None, retired_at: Optional[datetime] = None) -> bool:
        if self.backend:
            return await self.backend.update_agent_status(agent_id, status, paused_at=paused_at, retired_at=retired_at)
        return False

    async def delete_agent(self, agent_id: int) -> bool:
        if self.backend:
            return await self.backend.delete_agent(agent_id)
        return False

    # -- Agent Decisions CRUD (Facade) --

    async def create_agent_decision(self, decision: AgentDecision) -> Optional[int]:
        if self.backend:
            return await self.backend.create_agent_decision(decision)
        return None

    async def get_agent_decisions(self, agent_id: int, limit: int = 50) -> List[AgentDecision]:
        if self.backend:
            return await self.backend.get_agent_decisions(agent_id, limit)
        return []

    # -- Agent Performance CRUD (Facade) --

    async def upsert_agent_performance(self, perf: AgentPerformance) -> bool:
        if self.backend:
            return await self.backend.upsert_agent_performance(perf)
        return False

    async def get_agent_performance(self, agent_id: int, days: int = 30) -> List[AgentPerformance]:
        if self.backend:
            return await self.backend.get_agent_performance(agent_id, days)
        return []

    # -- Signal CRUD (Facade) --

    async def create_signal(self, signal: Signal) -> Optional[int]:
        if self.backend:
            return await self.backend.create_signal(signal)
        return None

    async def list_signals(self, limit: int = 50, source: Optional[str] = None) -> List[Signal]:
        if self.backend:
            return await self.backend.list_signals(limit, source)
        return []

    async def update_signal_status(self, signal_id: int, status: str, auto_executed: bool = False) -> bool:
        if self.backend:
            return await self.backend.update_signal_status(signal_id, status, auto_executed)
        return False

    # -- Audit Log (Facade) --

    async def log_audit(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        actor: str = "system",
        ip: Optional[str] = None,
    ) -> Optional[int]:
        if self.backend:
            return await self.backend.log_audit(
                action, resource_type, resource_id=resource_id,
                details=details, actor=actor, ip=ip,
            )
        return None

    # -- Trade Attribution CRUD (Facade) --

    async def create_trade_attribution(self, attr: TradeAttribution) -> Optional[int]:
        if self.backend:
            return await self.backend.create_trade_attribution(attr)
        return None

    async def close_trade_attribution(
        self, trade_id: str, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        if self.backend:
            return await self.backend.close_trade_attribution(
                trade_id, exit_price, realized_pnl,
                hold_duration_seconds, exit_reason,
            )
        return False

    async def close_oldest_open_attribution(
        self, agent_id: int, exit_price: float, realized_pnl: float,
        hold_duration_seconds: int, exit_reason: str,
    ) -> bool:
        if self.backend:
            return await self.backend.close_oldest_open_attribution(
                agent_id, exit_price, realized_pnl,
                hold_duration_seconds, exit_reason,
            )
        return False

    async def get_trade_attributions(
        self, agent_id: int, limit: int = 100, closed_only: bool = False,
    ) -> List[TradeAttribution]:
        if self.backend:
            return await self.backend.get_trade_attributions(agent_id, limit, closed_only)
        return []

    # -- Strategy Scorecard CRUD (Facade) --

    async def upsert_strategy_scorecard(self, sc: StrategyScorecard) -> bool:
        if self.backend:
            return await self.backend.upsert_strategy_scorecard(sc)
        return False

    async def get_strategy_scorecards(
        self, agent_id: int, strategy_name: Optional[str] = None,
    ) -> List[StrategyScorecard]:
        if self.backend:
            return await self.backend.get_strategy_scorecards(agent_id, strategy_name)
        return []

    # -- Param Mutation CRUD (Facade) --

    async def create_param_mutation(self, mutation: ParamMutation) -> Optional[int]:
        if self.backend:
            return await self.backend.create_param_mutation(mutation)
        return None

    async def get_param_mutations(
        self, agent_id: int, limit: int = 50, accepted_only: bool = False,
    ) -> List[ParamMutation]:
        if self.backend:
            return await self.backend.get_param_mutations(agent_id, limit, accepted_only)
        return []

    async def get_successful_mutations(
        self, strategy_name: str, min_sharpe_improvement: float = 0.1, days: int = 14,
    ) -> List[ParamMutation]:
        if self.backend:
            return await self.backend.get_successful_mutations(
                strategy_name, min_sharpe_improvement, days,
            )
        return []

    async def update_param_mutation_live_pnl(
        self, mutation_id: int, live_pnl: float,
    ) -> bool:
        if self.backend:
            return await self.backend.update_param_mutation_live_pnl(mutation_id, live_pnl)
        return False
