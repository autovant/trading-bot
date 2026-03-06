"""Alembic environment configuration.

Reads the database URL from the ``DATABASE_URL`` environment variable
(falls back to ``sqlite:///data/trading.db``).  Imports
``src.db_schema.metadata`` so ``alembic revision --autogenerate`` can diff
against the declared table definitions.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the project root is on sys.path so ``src.*`` imports work.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# -- Alembic Config object ---------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -- Target metadata ---------------------------------------------------------
# Import the declarative metadata from the project so autogenerate can detect
# model changes.  The app uses raw SQL at runtime but the schema is mirrored
# in src/db_schema.py for migration purposes.
from src.db_schema import metadata  # noqa: E402

target_metadata = metadata

# -- Database URL override ----------------------------------------------------

def _get_url() -> str:
    """Return the database URL, preferring the environment variable."""
    return os.environ.get("DATABASE_URL", "sqlite:///data/trading.db")


# -- Offline (SQL-script) migrations -----------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL script output instead of connecting to the database.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# -- Online (connected) migrations -------------------------------------------

def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
