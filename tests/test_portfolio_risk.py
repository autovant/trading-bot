"""
Unit tests for the portfolio risk manager.

Tests exposure limits, symbol concentration, correlation checks, and rate limiting.
"""

from __future__ import annotations

import pytest

from src.config import AgentRiskGuardrails
from src.risk.portfolio_risk import PortfolioRiskManager, RateLimitPool


# Default guardrails for test convenience
def _guardrails(**overrides) -> AgentRiskGuardrails:
    defaults = {
        "max_position_size_usd": 50_000.0,
        "max_open_positions": 10,
    }
    defaults.update(overrides)
    return AgentRiskGuardrails(**defaults)


# ---------------------------------------------------------------------------
# RateLimitPool
# ---------------------------------------------------------------------------

class TestRateLimitPool:
    """Test token-bucket rate limiter."""

    def test_initial_tokens(self):
        pool = RateLimitPool(capacity=10, fill_rate=1.0)
        assert pool.try_acquire() is True

    def test_exhaust_tokens(self):
        pool = RateLimitPool(capacity=2, fill_rate=0.0)
        assert pool.try_acquire() is True
        assert pool.try_acquire() is True
        assert pool.try_acquire() is False

    def test_acquire_n(self):
        pool = RateLimitPool(capacity=5, fill_rate=0.0)
        assert pool.try_acquire(3) is True
        assert pool.try_acquire(3) is False
        assert pool.try_acquire(2) is True
        assert pool.try_acquire(1) is False


# ---------------------------------------------------------------------------
# PortfolioRiskManager — Exposure limits
# ---------------------------------------------------------------------------

class TestPortfolioExposure:
    """Test total and per-agent exposure caps."""

    def test_order_within_limits(self):
        mgr = PortfolioRiskManager(
            max_total_exposure_usd=100_000,
            max_symbol_concentration_pct=0.50,
        )
        ok, reasons = mgr.check_order(1, "BTCUSDT", 10_000, _guardrails())
        assert ok is True
        assert reasons == []

    def test_order_exceeds_total_exposure(self):
        mgr = PortfolioRiskManager(
            max_total_exposure_usd=10_000,
            max_symbol_concentration_pct=0.50,
        )
        mgr.update_position(1, "BTCUSDT", 9_000)
        ok, reasons = mgr.check_order(2, "ETHUSDT", 2_000, _guardrails())
        assert ok is False
        assert any("total exposure" in r.lower() for r in reasons)

    def test_order_exceeds_per_agent_position_size(self):
        mgr = PortfolioRiskManager(
            max_total_exposure_usd=100_000,
            max_symbol_concentration_pct=0.50,
        )
        ok, reasons = mgr.check_order(
            1, "ETHUSDT", 6_000, _guardrails(max_position_size_usd=5_000)
        )
        assert ok is False
        assert any("exceeds" in r.lower() and "agent limit" in r.lower() for r in reasons)

    def test_symbol_concentration_breach(self):
        mgr = PortfolioRiskManager(
            max_total_exposure_usd=100_000,
            max_symbol_concentration_pct=0.30,
        )
        mgr.update_position(1, "BTCUSDT", 20_000)
        # Adding 15k BTC → BTC=35k, total=35k → 100% concentration > 30%
        ok, reasons = mgr.check_order(2, "BTCUSDT", 15_000, _guardrails())
        assert ok is False
        assert any("concentration" in r.lower() for r in reasons)


# ---------------------------------------------------------------------------
# PortfolioRiskManager — Correlation
# ---------------------------------------------------------------------------

class TestPortfolioCorrelation:
    """Test cross-agent correlation limits."""

    def test_uncorrelated_agents_pass(self):
        mgr = PortfolioRiskManager(max_agent_correlation=0.70)
        # Low-correlation returns (different patterns, not mirror images)
        for r in [0.01, -0.02, 0.03, -0.01, 0.02]:
            mgr.record_daily_return(1, r)
        for r in [0.005, 0.01, -0.005, -0.02, 0.015]:
            mgr.record_daily_return(2, r)
        ok, msg = mgr.check_correlation(1)
        assert ok is True
        assert msg is None

    def test_highly_correlated_agents_fail(self):
        mgr = PortfolioRiskManager(max_agent_correlation=0.70)
        returns = [0.01, 0.02, -0.01, 0.03, 0.015, -0.005, 0.025]
        for r in returns:
            mgr.record_daily_return(1, r)
            mgr.record_daily_return(2, r)  # identical → correlation = 1.0
        ok, msg = mgr.check_correlation(1)
        assert ok is False
        assert msg is not None
        assert "2" in msg  # references agent 2


# ---------------------------------------------------------------------------
# PortfolioRiskManager — Summary + Remove
# ---------------------------------------------------------------------------

class TestPortfolioSummary:
    """Test portfolio summary and agent removal."""

    def test_summary_structure(self):
        mgr = PortfolioRiskManager()
        mgr.update_position(1, "BTCUSDT", 10_000)
        mgr.update_position(2, "ETHUSDT", 5_000)
        summary = mgr.get_portfolio_summary()
        assert summary["total_exposure_usd"] == 15_000
        assert summary["active_agents"] == 2
        assert "BTCUSDT" in summary["symbol_exposures"]

    def test_remove_agent(self):
        mgr = PortfolioRiskManager()
        mgr.update_position(1, "BTCUSDT", 10_000)
        mgr.remove_agent(1)
        summary = mgr.get_portfolio_summary()
        assert summary["total_exposure_usd"] == 0
        assert summary["active_agents"] == 0

    def test_update_position_overwrites(self):
        mgr = PortfolioRiskManager()
        mgr.update_position(1, "BTCUSDT", 10_000)
        mgr.update_position(1, "BTCUSDT", 5_000)
        summary = mgr.get_portfolio_summary()
        assert summary["total_exposure_usd"] == 5_000

    def test_rate_limit_pool_integration(self):
        mgr = PortfolioRiskManager()
        pool = mgr.get_rate_pool("bybit")
        # Exhaust the default pool
        while pool.try_acquire():
            pass
        assert mgr.try_acquire_rate("bybit") is False
