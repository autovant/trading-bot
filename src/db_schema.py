"""
SQLAlchemy table definitions mirroring the existing raw-SQL schema in
``src/database.py``.  This module exists solely to give Alembic a
``MetaData`` object for autogenerate support.  It is **not** used at runtime
by the application — the app continues to use raw asyncpg / aiosqlite queries.

Keep these definitions in sync with the DDL in
``PostgresBackend._ensure_schema`` and ``SQLiteBackend._ensure_schema``.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

# ── Orders ──────────────────────────────────────────────────────────────────

orders = sa.Table(
    "orders",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("client_id", sa.Text, unique=True, nullable=False),
    sa.Column("order_id", sa.Text, unique=True),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("order_type", sa.Text, nullable=False),
    sa.Column("quantity", sa.Float, nullable=False),
    sa.Column("price", sa.Float),
    sa.Column("stop_price", sa.Float),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("latency_ms", sa.Float),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

orders_shadow = sa.Table(
    "orders_shadow",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("client_id", sa.Text, unique=True, nullable=False),
    sa.Column("order_id", sa.Text, unique=True),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("order_type", sa.Text, nullable=False),
    sa.Column("quantity", sa.Float, nullable=False),
    sa.Column("price", sa.Float),
    sa.Column("stop_price", sa.Float),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("latency_ms", sa.Float),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Trades ──────────────────────────────────────────────────────────────────

trades = sa.Table(
    "trades",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("client_id", sa.Text, unique=True, nullable=False),
    sa.Column("trade_id", sa.Text, unique=True, nullable=False),
    sa.Column("order_id", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("quantity", sa.Float, nullable=False),
    sa.Column("price", sa.Float, nullable=False),
    sa.Column("commission", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("fees", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("funding", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("realized_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("mark_price", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("slippage_bps", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column(
        "achieved_vs_signal_bps", sa.Float, nullable=False, server_default=sa.text("0")
    ),
    sa.Column("latency_ms", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("maker", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

trades_shadow = sa.Table(
    "trades_shadow",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("client_id", sa.Text, unique=True, nullable=False),
    sa.Column("trade_id", sa.Text, unique=True, nullable=False),
    sa.Column("order_id", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("quantity", sa.Float, nullable=False),
    sa.Column("price", sa.Float, nullable=False),
    sa.Column("commission", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("fees", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("funding", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("realized_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("mark_price", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("slippage_bps", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column(
        "achieved_vs_signal_bps", sa.Float, nullable=False, server_default=sa.text("0")
    ),
    sa.Column("latency_ms", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("maker", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Positions ───────────────────────────────────────────────────────────────

positions = sa.Table(
    "positions",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("size", sa.Float, nullable=False),
    sa.Column("entry_price", sa.Float, nullable=False),
    sa.Column("mark_price", sa.Float, nullable=False),
    sa.Column("unrealized_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("percentage", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.UniqueConstraint("symbol", "mode", "run_id"),
)

# ── Order Intents ───────────────────────────────────────────────────────────

order_intents = sa.Table(
    "order_intents",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("idempotency_key", sa.Text, unique=True, nullable=False),
    sa.Column("client_id", sa.Text, unique=True, nullable=False),
    sa.Column("order_id", sa.Text),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("order_type", sa.Text, nullable=False),
    sa.Column("quantity", sa.Float, nullable=False),
    sa.Column("price", sa.Float),
    sa.Column("stop_price", sa.Float),
    sa.Column("reduce_only", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("filled_qty", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("avg_fill_price", sa.Float),
    sa.Column("last_error", sa.Text),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Order Intent Events ────────────────────────────────────────────────────

order_intent_events = sa.Table(
    "order_intent_events",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("idempotency_key", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("details", sa.Text),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Order Fills ─────────────────────────────────────────────────────────────

order_fills = sa.Table(
    "order_fills",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("idempotency_key", sa.Text, nullable=False),
    sa.Column("trade_id", sa.Text, unique=True, nullable=False),
    sa.Column("order_id", sa.Text),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("quantity", sa.Float, nullable=False),
    sa.Column("price", sa.Float, nullable=False),
    sa.Column("fee", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Strategies ──────────────────────────────────────────────────────────────

strategies = sa.Table(
    "strategies",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("config", sa.JSON, nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── PnL Entries ─────────────────────────────────────────────────────────────

pnl_entries = sa.Table(
    "pnl_entries",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("trade_id", sa.Text, unique=True, nullable=False),
    sa.Column("realized_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("unrealized_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("commission", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("fees", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("funding", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("net_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("balance", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Credentials ─────────────────────────────────────────────────────────────

credentials = sa.Table(
    "credentials",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("exchange_id", sa.Text, nullable=False),
    sa.Column("label", sa.Text, nullable=False),
    sa.Column("api_key_enc", sa.Text, nullable=False),
    sa.Column("api_secret_enc", sa.Text, nullable=False),
    sa.Column("passphrase_enc", sa.Text),
    sa.Column("is_testnet", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Backtest Jobs ───────────────────────────────────────────────────────────

backtest_jobs = sa.Table(
    "backtest_jobs",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("job_id", sa.Text, unique=True, nullable=False),
    sa.Column("strategy_id", sa.Integer),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("start_date", sa.Text, nullable=False),
    sa.Column("end_date", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
    sa.Column("result_json", sa.JSON),
    sa.Column("error", sa.Text),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
)

# ── Agents ──────────────────────────────────────────────────────────────────

agents = sa.Table(
    "agents",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'created'")),
    sa.Column("config_json", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
    sa.Column("allocation_usd", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("strategy_name", sa.Text),
    sa.Column("strategy_params", sa.JSON),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column("paused_at", sa.DateTime(timezone=True)),
    sa.Column("retired_at", sa.DateTime(timezone=True)),
)

# ── Agent Decisions ─────────────────────────────────────────────────────────

agent_decisions = sa.Table(
    "agent_decisions",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "agent_id",
        sa.Integer,
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column("phase", sa.Text, nullable=False),
    sa.Column("market_snapshot_json", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
    sa.Column("decision_json", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
    sa.Column("outcome_json", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
    sa.Column("trade_ids", sa.Text, nullable=False, server_default=sa.text("'{}'")),
)

# ── Agent Performance ──────────────────────────────────────────────────────

agent_performance = sa.Table(
    "agent_performance",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "agent_id",
        sa.Integer,
        sa.ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("date", sa.Date, nullable=False),
    sa.Column("realized_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("unrealized_pnl", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("total_trades", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("win_rate", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("sharpe_rolling_30d", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("max_drawdown", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.Column("equity", sa.Float, nullable=False, server_default=sa.text("0")),
    sa.UniqueConstraint("agent_id", "date"),
)

# ── Signals ─────────────────────────────────────────────────────────────────

signals = sa.Table(
    "signals",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("symbol", sa.Text, nullable=False),
    sa.Column("side", sa.Text, nullable=False),
    sa.Column("confidence", sa.Float),
    sa.Column("entry_price", sa.Float),
    sa.Column("stop_loss", sa.Float),
    sa.Column("take_profit", sa.Float),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'received'")),
    sa.Column("auto_executed", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
    sa.Column(
        "agent_id",
        sa.Integer,
        sa.ForeignKey("agents.id", ondelete="SET NULL"),
    ),
    sa.Column("raw_payload", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Config Versions ─────────────────────────────────────────────────────────

config_versions = sa.Table(
    "config_versions",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("version", sa.Text, nullable=False),
    sa.Column("config", sa.Text, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Risk Snapshots ──────────────────────────────────────────────────────────

risk_snapshots = sa.Table(
    "risk_snapshots",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("crisis_mode", sa.Boolean, nullable=False),
    sa.Column("consecutive_losses", sa.Integer, nullable=False),
    sa.Column("drawdown", sa.Float, nullable=False),
    sa.Column("volatility", sa.Float, nullable=False),
    sa.Column("position_size_factor", sa.Float, nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
)

# ── Audit Log ───────────────────────────────────────────────────────────────

audit_log = sa.Table(
    "audit_log",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column(
        "timestamp",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    ),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("actor", sa.Text, nullable=False, server_default=sa.text("'system'")),
    sa.Column("resource_type", sa.Text, nullable=False),
    sa.Column("resource_id", sa.Text),
    sa.Column("details_json", sa.Text),
    sa.Column("ip_address", sa.Text),
)
