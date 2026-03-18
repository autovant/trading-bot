"""Tests for the risk manager."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.config import RiskConfig
from src.models import CopySignal, SourceTrade, TradeSide
from src.risk_manager import RiskManager


def _make_signal(price: float = 0.5, size: float = 50.0, asset_id: str = "token-001") -> CopySignal:
    """Helper to create a CopySignal for testing."""
    return CopySignal(
        source_trade=SourceTrade(
            trade_id="t1",
            wallet="0xabc",
            market_id="m1",
            asset_id=asset_id,
            side=TradeSide.BUY,
            price=price,
            size=size,
        ),
        target_side=TradeSide.BUY,
        target_price=price,
        target_size=size,
    )


class TestRiskManager:
    def test_allow_normal_trade(self, risk_config):
        rm = RiskManager(risk_config)
        result = rm.check(_make_signal(price=0.5, size=10.0))
        assert result.allowed is True

    def test_reject_high_price(self, risk_config):
        rm = RiskManager(risk_config)
        result = rm.check(_make_signal(price=0.99))
        assert result.allowed is False
        assert "max" in result.reason.lower()

    def test_reject_low_price(self, risk_config):
        rm = RiskManager(risk_config)
        result = rm.check(_make_signal(price=0.02))
        assert result.allowed is False
        assert "min" in result.reason.lower()

    def test_max_open_positions(self, risk_config):
        rm = RiskManager(risk_config)
        # Fill up to max_open_positions (3)
        for i in range(3):
            rm.record_fill(f"token-{i}", "BUY", 10.0, 0.5, f"market-{i}")
        result = rm.check(_make_signal(asset_id="token-new"))
        assert result.allowed is False
        assert "positions" in result.reason.lower()

    def test_existing_position_allowed(self, risk_config):
        rm = RiskManager(risk_config)
        for i in range(3):
            rm.record_fill(f"token-{i}", "BUY", 10.0, 0.5, f"market-{i}")
        # Signal for existing position should be allowed
        result = rm.check(_make_signal(price=0.5, size=5.0, asset_id="token-0"))
        assert result.allowed is True

    def test_portfolio_exposure_limit(self, risk_config):
        rm = RiskManager(risk_config)
        # Fill 180 USDC of exposure (limit is 200)
        rm.record_fill("token-a", "BUY", 360.0, 0.5, "m1")
        # Try to add 50 USDC more (360*0.5 + 100*0.5 = 180 + 50 = 230 > 200)
        result = rm.check(_make_signal(price=0.5, size=100.0, asset_id="token-b"))
        assert result.allowed is True
        assert result.adjusted_size is not None
        assert result.adjusted_size < 100.0

    def test_consecutive_loss_circuit_breaker(self, risk_config):
        rm = RiskManager(risk_config)
        # Create position
        rm.record_fill("token-x", "BUY", 100.0, 0.5, "m1")
        # Simulate 3 consecutive losses
        for _ in range(3):
            rm.record_fill("token-x", "BUY", 100.0, 0.5, "m1")
            rm.record_fill("token-x", "SELL", 100.0, 0.4, "m1")  # loss

        assert rm.is_paused is True
        result = rm.check(_make_signal())
        assert result.allowed is False
        assert "circuit breaker" in result.reason.lower()

    def test_resume_after_pause(self, risk_config):
        rm = RiskManager(risk_config)
        rm._paused = True
        rm.resume()
        assert rm.is_paused is False

    def test_daily_loss_limit(self, risk_config):
        risk_config.daily_loss_limit_usdc = 10.0
        rm = RiskManager(risk_config)
        # Create and sell at a loss: loss = (0.3 - 0.5) * 100 = -20
        rm.record_fill("token-y", "BUY", 100.0, 0.5, "m1")
        rm.record_fill("token-y", "SELL", 100.0, 0.3, "m1")
        result = rm.check(_make_signal())
        assert result.allowed is False
        assert "daily loss" in result.reason.lower()

    def test_snapshot(self, risk_config):
        rm = RiskManager(risk_config)
        rm.record_fill("token-s", "BUY", 50.0, 0.6, "m1")
        snap = rm.get_snapshot()
        assert snap.open_positions == 1
        assert snap.total_exposure_usdc > 0
