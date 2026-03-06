"""Walk-forward optimizer and Monte Carlo simulator unit tests (4.1.5).

These tests use mock/synthetic data — no exchange or external dependencies.
For integration tests with realistic generated data, see test_strategy_real_data.py.
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pytest

from src.backtest.monte_carlo import MonteCarloResult, MonteCarloSimulator
from src.backtest.walk_forward import WalkForwardOptimizer, WalkForwardResult


# ── Walk-Forward Optimizer ───────────────────────────────────────────────────


class TestWalkForwardInstantiation:
    """Constructor validation and defaults."""

    def test_default_params(self):
        wfo = WalkForwardOptimizer()
        assert wfo.num_windows == 5
        assert wfo.ratio == 0.70
        assert wfo.min_oos_sharpe == 0.5
        assert wfo.max_degradation_pct == 50.0

    def test_custom_params(self):
        wfo = WalkForwardOptimizer(
            num_windows=3, ratio=0.80, min_oos_sharpe=0.3, max_degradation_pct=40.0
        )
        assert wfo.num_windows == 3
        assert wfo.ratio == 0.80

    def test_invalid_num_windows(self):
        with pytest.raises(ValueError, match="num_windows must be >= 2"):
            WalkForwardOptimizer(num_windows=1)

    def test_invalid_ratio_low(self):
        with pytest.raises(ValueError, match="ratio must be between"):
            WalkForwardOptimizer(ratio=0.05)

    def test_invalid_ratio_high(self):
        with pytest.raises(ValueError, match="ratio must be between"):
            WalkForwardOptimizer(ratio=0.99)


class TestWalkForwardRun:
    """Walk-forward run with mock backtest function."""

    @pytest.fixture
    def mock_backtest_fn(self):
        """Return a mock backtest function producing deterministic results."""
        rng = np.random.default_rng(42)

        async def backtest(
            symbol: str, start: str, end: str, **kwargs: Any
        ) -> Dict[str, Any]:
            sharpe = float(rng.normal(1.0, 0.3))
            trades = int(rng.integers(10, 50))
            pnl = float(rng.normal(500, 200))
            return {
                "sharpe_ratio": sharpe,
                "total_trades": trades,
                "total_pnl": pnl,
                "max_drawdown": float(rng.uniform(5, 25)),
                "win_rate": float(rng.uniform(40, 60)),
            }

        return backtest

    async def test_walk_forward_basic_run(self, mock_backtest_fn):
        """WFO produces correct number of windows with populated metrics."""
        wfo = WalkForwardOptimizer(
            num_windows=3,
            ratio=0.70,
            min_oos_sharpe=-999,
            max_degradation_pct=999,
        )
        result = await wfo.run(
            backtest_fn=mock_backtest_fn,
            symbol="BTCUSDT",
            start_date="2024-01-01",
            end_date="2024-07-01",
        )

        assert isinstance(result, WalkForwardResult)
        assert result.num_windows == 3
        assert len(result.windows) == 3

        for w in result.windows:
            assert w.in_sample_start < w.in_sample_end
            assert w.out_sample_start <= w.out_sample_end
            assert isinstance(w.in_sample_sharpe, float)
            assert isinstance(w.out_sample_sharpe, float)
            assert isinstance(w.degradation_pct, float)

    async def test_walk_forward_aggregate_metrics(self, mock_backtest_fn):
        """Aggregate OOS Sharpe and degradation are computed."""
        wfo = WalkForwardOptimizer(
            num_windows=4,
            ratio=0.70,
            min_oos_sharpe=-999,
            max_degradation_pct=999,
        )
        result = await wfo.run(
            backtest_fn=mock_backtest_fn,
            symbol="SOLUSDT",
            start_date="2024-01-01",
            end_date="2024-06-01",
        )

        assert isinstance(result.aggregate_oos_sharpe, float)
        assert isinstance(result.mean_degradation_pct, float)
        assert isinstance(result.aggregate_oos_pnl, float)
        # Passed is set (with relaxed thresholds it should pass)
        assert result.passed is True

    async def test_walk_forward_fail_low_sharpe(self):
        """WFO fails when OOS Sharpe is below threshold."""

        async def bad_backtest(symbol: str, start: str, end: str, **kw):
            return {
                "sharpe_ratio": -0.5,
                "total_trades": 20,
                "total_pnl": -100,
                "max_drawdown": 30,
                "win_rate": 30,
            }

        wfo = WalkForwardOptimizer(
            num_windows=2, ratio=0.70, min_oos_sharpe=0.5, max_degradation_pct=999
        )
        result = await wfo.run(
            backtest_fn=bad_backtest,
            symbol="BTCUSDT",
            start_date="2024-01-01",
            end_date="2024-06-01",
        )

        assert result.passed is False
        assert any("OOS Sharpe" in r for r in result.failure_reasons)

    async def test_walk_forward_windows_are_sequential(self, mock_backtest_fn):
        """Window date ranges should be non-overlapping and sequential."""
        wfo = WalkForwardOptimizer(num_windows=3, ratio=0.70,
                                    min_oos_sharpe=-999, max_degradation_pct=999)
        result = await wfo.run(
            backtest_fn=mock_backtest_fn,
            symbol="BTCUSDT",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        for i in range(len(result.windows) - 1):
            current = result.windows[i]
            next_w = result.windows[i + 1]
            # Current OOS end should be at or before next IS start
            assert current.out_sample_end <= next_w.in_sample_start or \
                   current.out_sample_end == next_w.in_sample_start


# ── Monte Carlo Simulator ───────────────────────────────────────────────────


class TestMonteCarloInstantiation:
    """Constructor and edge-case validation."""

    def test_default_params(self):
        mc = MonteCarloSimulator()
        assert mc.num_simulations == 1000
        assert mc.max_drawdown_limit == 0.30

    def test_custom_params(self):
        mc = MonteCarloSimulator(
            num_simulations=500, seed=42, max_drawdown_limit=0.20
        )
        assert mc.num_simulations == 500
        assert mc.max_drawdown_limit == 0.20

    def test_insufficient_trades(self):
        mc = MonteCarloSimulator(num_simulations=100, seed=1)
        result = mc.run([50.0], initial_equity=10_000)
        assert result.passed is False
        assert result.num_simulations == 0
        assert any("Insufficient" in r for r in result.failure_reasons)


class TestMonteCarloRun:
    """Core Monte Carlo simulation with synthetic trade data."""

    @pytest.fixture
    def profitable_trades(self) -> list[float]:
        """50 trades with slight positive edge."""
        rng = np.random.default_rng(42)
        return [float(rng.normal(10, 50)) for _ in range(50)]

    @pytest.fixture
    def losing_trades(self) -> list[float]:
        """50 trades with strong negative edge."""
        rng = np.random.default_rng(42)
        return [float(rng.normal(-30, 20)) for _ in range(50)]

    def test_monte_carlo_basic_run(self, profitable_trades):
        """MC simulation produces valid percentile distributions."""
        mc = MonteCarloSimulator(num_simulations=200, seed=42)
        result = mc.run(profitable_trades, initial_equity=10_000)

        assert isinstance(result, MonteCarloResult)
        assert result.num_simulations == 200
        assert result.initial_equity == 10_000

        # Percentile ordering
        assert result.final_equity_p5 <= result.final_equity_p25
        assert result.final_equity_p25 <= result.final_equity_p50
        assert result.final_equity_p50 <= result.final_equity_p75
        assert result.final_equity_p75 <= result.final_equity_p95

        # Drawdown percentile ordering
        assert result.max_dd_p5 <= result.max_dd_p50
        assert result.max_dd_p50 <= result.max_dd_p95

        # Drawdowns are in [0, 1] range
        assert 0.0 <= result.max_dd_p5 <= 1.0
        assert 0.0 <= result.max_dd_p95 <= 1.0

    def test_monte_carlo_deterministic(self, profitable_trades):
        """Same seed produces identical results."""
        mc1 = MonteCarloSimulator(num_simulations=100, seed=123)
        mc2 = MonteCarloSimulator(num_simulations=100, seed=123)

        r1 = mc1.run(profitable_trades, initial_equity=10_000)
        r2 = mc2.run(profitable_trades, initial_equity=10_000)

        assert r1.final_equity_p50 == r2.final_equity_p50
        assert r1.max_dd_p95 == r2.max_dd_p95

    def test_monte_carlo_losing_strategy_fails(self, losing_trades):
        """MC with losing trades should fail final equity check."""
        mc = MonteCarloSimulator(
            num_simulations=200,
            seed=42,
            min_final_equity_ratio=1.0,
        )
        result = mc.run(losing_trades, initial_equity=10_000)

        assert result.passed is False
        assert result.final_equity_p5 < 10_000

    def test_monte_carlo_distributions_populated(self, profitable_trades):
        """equity_distribution and drawdown_distribution lists are filled."""
        mc = MonteCarloSimulator(num_simulations=50, seed=42)
        result = mc.run(profitable_trades, initial_equity=10_000)

        assert len(result.equity_distribution) == 50
        assert len(result.drawdown_distribution) == 50

    def test_monte_carlo_extract_trade_returns(self):
        """Static helper extracts P&L from backtest result dicts."""
        backtest_result = {
            "trade_history": [
                {"pnl": 100.0},
                {"pnl": -50.0},
                {"pnl": 75.0},
            ]
        }
        returns = MonteCarloSimulator.extract_trade_returns(backtest_result)
        assert returns == [100.0, -50.0, 75.0]

    def test_monte_carlo_extract_trade_returns_empty(self):
        """Extract returns from empty backtest result."""
        returns = MonteCarloSimulator.extract_trade_returns({})
        assert returns == []
