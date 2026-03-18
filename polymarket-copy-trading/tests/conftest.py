"""Shared test fixtures."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AppConfig, CopyConfig, PolymarketConfig, RiskConfig
from src.models import SourceTrade, TradeSide


@pytest.fixture
def default_config() -> AppConfig:
    """Minimal test configuration."""
    return AppConfig(
        polymarket=PolymarketConfig(private_key=""),
        source_wallets=["0xabc123", "0xdef456"],
        poll_interval_seconds=5,
        dry_run=True,
    )


@pytest.fixture
def risk_config() -> RiskConfig:
    """Risk config with small limits for testing."""
    return RiskConfig(
        max_position_size_usdc=100.0,
        max_portfolio_exposure_usdc=200.0,
        max_open_positions=3,
        slippage_tolerance_pct=2.0,
        max_price=0.95,
        min_price=0.05,
        daily_loss_limit_usdc=50.0,
        max_consecutive_losses=3,
    )


@pytest.fixture
def sample_source_trade() -> SourceTrade:
    """A realistic source trade for testing."""
    return SourceTrade(
        trade_id="trade-001",
        wallet="0xabc123def456789",
        market_id="market-001",
        asset_id="token-001",
        side=TradeSide.BUY,
        price=0.65,
        size=50.0,
        timestamp=datetime.now(timezone.utc),
        market_question="Will event X happen?",
        outcome="Yes",
    )


@pytest.fixture
def tmp_db_path(tmp_path) -> str:
    """Temporary database path."""
    return f"sqlite:///{tmp_path / 'test.db'}"
