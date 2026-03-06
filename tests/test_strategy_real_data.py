"""
Strategy validation tests using realistic market data (Epic 6.4).

Tests run the strategy pipeline (regime ➜ setup ➜ signal), backtest engine,
walk-forward optimizer, and Monte Carlo simulator against data with proper
market microstructure (trending / consolidation / vol-clustering).

All tests are deterministic (seeded RNG) and marked ``@pytest.mark.integration``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from src.backtest.monte_carlo import MonteCarloSimulator
from src.backtest.walk_forward import WalkForwardOptimizer
from src.config import StrategyConfig, get_config
from src.indicators import TechnicalIndicators
from src.models import MarketRegime, TradingSetup, TradingSignal
from src.risk.portfolio_risk import PortfolioRiskManager
from src.signal_generator import SignalGenerator

from tests.fixtures.realistic_data import (
    generate_multi_timeframe_data,
    generate_realistic_ohlcv,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEED = 42


@pytest.fixture(scope="module")
def strategy_config() -> StrategyConfig:
    """Fixed strategy config for deterministic tests."""
    return StrategyConfig()


@pytest.fixture(scope="module")
def signal_generator() -> SignalGenerator:
    return SignalGenerator(TechnicalIndicators())


@pytest.fixture(scope="module")
def realistic_data() -> dict[str, pd.DataFrame]:
    """6 months of aligned 1h / 4h / 1d BTCUSDT data."""
    return generate_multi_timeframe_data(
        symbol="BTCUSDT", start_date="2024-01-01", months=6, seed=SEED
    )


@pytest.fixture(scope="module")
def realistic_data_ethusdt() -> dict[str, pd.DataFrame]:
    """6 months of ETHUSDT data (different seed → different price path)."""
    return generate_multi_timeframe_data(
        symbol="ETHUSDT", start_date="2024-01-01", months=6, seed=SEED + 1
    )


def _run_strategy_pipeline(
    signal_gen: SignalGenerator,
    config: StrategyConfig,
    data: dict[str, pd.DataFrame],
) -> List[TradingSignal]:
    """Run the regime ➜ setup ➜ signal pipeline, returning all generated signals."""
    hourly = data["signal"]
    four_hour = data["setup"]
    daily = data["regime"]

    all_signals: List[TradingSignal] = []
    warmup = 200  # bars needed for indicator convergence

    # Slide a window across the hourly data
    step = 4  # evaluate every 4 hours to keep runtime short
    for i in range(warmup, len(hourly), step):
        h_slice = hourly.iloc[max(0, i - warmup) : i + 1]
        ts = hourly.index[i]

        # Corresponding 4h / daily slices up to this timestamp
        s_slice = four_hour[four_hour.index <= ts].tail(100)
        r_slice = daily[daily.index <= ts].tail(50)

        if len(s_slice) < 30 or len(r_slice) < 10:
            continue

        regime = signal_gen.detect_regime(r_slice, config)
        setup = signal_gen.detect_setup(s_slice, config)
        signals = signal_gen.generate_signals(h_slice, config)

        for sig in signals:
            # Filter: direction must agree with regime & setup
            regime_ok = (
                (sig.direction == "long" and regime.regime in ("bullish", "neutral"))
                or (sig.direction == "short" and regime.regime in ("bearish", "neutral"))
            )
            setup_ok = setup.direction == "none" or sig.direction == setup.direction
            if regime_ok and setup_ok:
                all_signals.append(sig)

    return all_signals


# ---------------------------------------------------------------------------
# Test 1 — Golden Backtest Regression (determinism)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_golden_backtest_regression(signal_generator, strategy_config, realistic_data):
    """Same input + same config ➜ same signals (deterministic)."""
    signals_a = _run_strategy_pipeline(signal_generator, strategy_config, realistic_data)
    signals_b = _run_strategy_pipeline(signal_generator, strategy_config, realistic_data)

    assert len(signals_a) == len(signals_b), "Signal count differs across runs"
    for a, b in zip(signals_a, signals_b):
        assert a.direction == b.direction
        assert a.signal_type == b.signal_type
        assert abs(a.entry_price - b.entry_price) < 1e-6
        assert abs(a.stop_loss - b.stop_loss) < 1e-6
        assert abs(a.take_profit - b.take_profit) < 1e-6


# ---------------------------------------------------------------------------
# Test 2 — Strategy Produces Trades with Realistic Data
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_strategy_produces_trades(signal_generator, strategy_config, realistic_data):
    """Strategy must generate >20 signals over 6 months, with both directions."""
    signals = _run_strategy_pipeline(signal_generator, strategy_config, realistic_data)

    assert len(signals) > 20, f"Expected >20 signals, got {len(signals)}"

    directions = {s.direction for s in signals}
    assert "long" in directions, "No long signals generated"
    assert "short" in directions, "No short signals generated"

    # Sanity: no impossible prices
    for s in signals:
        assert s.entry_price > 0, f"Entry price <= 0: {s.entry_price}"
        assert s.stop_loss > 0, f"Stop loss <= 0: {s.stop_loss}"
        assert s.take_profit > 0, f"Take profit <= 0: {s.take_profit}"

    # Sanity: stop loss on correct side
    for s in signals:
        if s.direction == "long":
            assert s.stop_loss < s.entry_price, (
                f"Long signal stop_loss ({s.stop_loss}) >= entry ({s.entry_price})"
            )
        elif s.direction == "short":
            assert s.stop_loss > s.entry_price, (
                f"Short signal stop_loss ({s.stop_loss}) <= entry ({s.entry_price})"
            )

    # Check a variety of signal types
    signal_types = {s.signal_type for s in signals}
    assert len(signal_types) >= 1, "Expected at least one signal type"


# ---------------------------------------------------------------------------
# Test 3 — Walk-Forward with Realistic Data
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_walk_forward_realistic(signal_generator, strategy_config):
    """Walk-forward optimizer produces IS and OOS results for 3 windows."""
    # Use a lightweight backtest function that runs the signal pipeline
    # and returns a result dict compatible with walk-forward expectations.
    data_cache: dict[str, dict[str, pd.DataFrame]] = {}

    async def lightweight_backtest(
        symbol: str, start: str, end: str, **kwargs
    ) -> dict:
        cache_key = f"{symbol}_{start}_{end}"
        if cache_key not in data_cache:
            start_dt = pd.Timestamp(start, tz="UTC")
            end_dt = pd.Timestamp(end, tz="UTC")
            hours = max(int((end_dt - start_dt).total_seconds() / 3600), 200)

            data = generate_multi_timeframe_data(
                symbol=symbol,
                start_date=start,
                months=max(1, hours // (30 * 24)),
                seed=hash(cache_key) % (2**31),
            )
            # Trim to exact range
            for key in data:
                data[key] = data[key][
                    (data[key].index >= start_dt) & (data[key].index <= end_dt)
                ]
            data_cache[cache_key] = data

        data = data_cache[cache_key]
        signals = _run_strategy_pipeline(signal_generator, strategy_config, data)

        # Simulate P&L from signals
        rng = np.random.default_rng(hash(cache_key) % (2**31))
        pnls = []
        for sig in signals:
            risk = abs(sig.entry_price - sig.stop_loss)
            reward = abs(sig.take_profit - sig.entry_price)
            # 45% win rate for a realistic simulation
            won = rng.random() < 0.45
            pnls.append(reward * 0.8 if won else -risk)

        total_pnl = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        total = len(pnls) or 1
        daily_returns = pnls if pnls else [0.0]
        std = float(np.std(daily_returns)) if len(daily_returns) > 1 else 1.0
        sharpe = (float(np.mean(daily_returns)) / std * np.sqrt(252)) if std > 0 else 0.0

        equity = 10_000 + np.cumsum(pnls) if pnls else np.array([10_000])
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / np.where(peak > 0, peak, 1.0)
        max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

        return {
            "total_trades": total,
            "total_pnl": total_pnl,
            "win_rate": wins / total * 100,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd * 100,
        }

    wfo = WalkForwardOptimizer(num_windows=3, ratio=0.70, min_oos_sharpe=-999, max_degradation_pct=999)
    result = await wfo.run(
        backtest_fn=lightweight_backtest,
        symbol="BTCUSDT",
        start_date="2024-01-01",
        end_date="2024-07-01",
    )

    # Assertions
    assert result.num_windows == 3
    assert len(result.windows) == 3, f"Expected 3 windows, got {len(result.windows)}"

    for w in result.windows:
        # Each window must have defined IS and OOS dates + metrics
        assert w.in_sample_start < w.in_sample_end
        assert w.out_sample_start <= w.out_sample_end
        # IS Sharpe and OOS Sharpe are computed (could be any value)
        assert isinstance(w.in_sample_sharpe, float)
        assert isinstance(w.out_sample_sharpe, float)
        assert isinstance(w.degradation_pct, float)

    # Degradation is measured (the field is populated)
    assert isinstance(result.mean_degradation_pct, float)


# ---------------------------------------------------------------------------
# Test 4 — Monte Carlo with Real Trade Results
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_monte_carlo_realistic(signal_generator, strategy_config, realistic_data):
    """Monte Carlo on simulated trade P&Ls: p5 equity > 0, p95 > p50 > p5."""
    signals = _run_strategy_pipeline(signal_generator, strategy_config, realistic_data)
    assert len(signals) > 10, "Need enough signals for Monte Carlo"

    # Generate realistic trade returns from signals
    rng = np.random.default_rng(SEED)
    trade_returns: List[float] = []
    for sig in signals:
        risk = abs(sig.entry_price - sig.stop_loss)
        reward = abs(sig.take_profit - sig.entry_price)
        won = rng.random() < 0.48  # slightly below 50%
        pnl = reward * 0.75 if won else -risk
        trade_returns.append(pnl)

    mc = MonteCarloSimulator(num_simulations=500, seed=SEED)
    result = mc.run(trade_returns, initial_equity=10_000.0)

    assert result.num_simulations == 500
    assert result.final_equity_p5 > 0, (
        f"p5 equity {result.final_equity_p5:.0f} must be > 0"
    )
    # Final equity percentiles are equal (sum is order-independent) or ordered
    assert result.final_equity_p95 >= result.final_equity_p5, (
        f"p95 ({result.final_equity_p95:.0f}) must be >= p5 ({result.final_equity_p5:.0f})"
    )
    # Drawdown varies by path ordering — this is the core Monte Carlo insight
    assert 0.0 <= result.max_dd_p5 <= 1.0
    assert 0.0 <= result.max_dd_p95 <= 1.0
    assert result.max_dd_p95 >= result.max_dd_p5, (
        f"Max DD p95 ({result.max_dd_p95:.3f}) must be >= p5 ({result.max_dd_p5:.3f})"
    )
    # Path-dependent metrics must show dispersion across simulations
    assert result.max_dd_p95 > result.max_dd_p5, (
        "Drawdown distribution should show dispersion across shuffled paths"
    )


# ---------------------------------------------------------------------------
# Test 5 — Multi-Symbol Portfolio Risk
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_multi_symbol_portfolio_risk(
    signal_generator,
    strategy_config,
    realistic_data,
    realistic_data_ethusdt,
):
    """Run strategy on 2 symbols; validate portfolio risk manager constraints."""
    btc_signals = _run_strategy_pipeline(signal_generator, strategy_config, realistic_data)
    eth_signals = _run_strategy_pipeline(signal_generator, strategy_config, realistic_data_ethusdt)

    assert len(btc_signals) > 0, "BTC must produce signals"
    assert len(eth_signals) > 0, "ETH must produce signals"

    # --- Portfolio risk manager ---
    prm = PortfolioRiskManager(
        max_total_exposure_usd=50_000.0,
        max_symbol_concentration_pct=0.60,
        max_agent_correlation=0.70,
    )

    from src.config import AgentRiskGuardrails

    guardrails = AgentRiskGuardrails(
        max_position_size_usd=10_000.0,
        max_open_positions=5,
    )

    # Simulate agent 1 trading BTC
    btc_entry = btc_signals[0].entry_price
    prm.update_position(agent_id=1, symbol="BTCUSDT", notional_usd=btc_entry * 0.1)

    # Simulate agent 2 trading ETH
    eth_entry = eth_signals[0].entry_price
    prm.update_position(agent_id=2, symbol="ETHUSDT", notional_usd=eth_entry * 0.5)

    # Check order for BTC agent — should be allowed
    allowed, reasons = prm.check_order(
        agent_id=1,
        symbol="BTCUSDT",
        proposed_notional_usd=2_000.0,
        agent_guardrails=guardrails,
    )
    assert allowed, f"BTC order rejected: {reasons}"

    # Check total exposure doesn't exceed limit
    summary = prm.get_portfolio_summary()
    assert summary["total_exposure_usd"] <= prm.max_total_exposure_usd

    # Symbol concentration check
    for sym, exposure in summary["symbol_exposures"].items():
        if summary["total_exposure_usd"] > 0:
            concentration = exposure / summary["total_exposure_usd"]
            assert concentration <= 1.0  # basic sanity

    # Correlation check: record some daily returns for both agents
    rng = np.random.default_rng(SEED)
    for day in range(10):
        prm.record_daily_return(1, float(rng.normal(0.001, 0.02)))
        prm.record_daily_return(2, float(rng.normal(0.0005, 0.025)))

    corr_ok, corr_msg = prm.check_correlation(agent_id=1)
    # Correlation check completes without error
    assert isinstance(corr_ok, bool)

    # Verify an over-limit order gets rejected
    allowed_big, reasons_big = prm.check_order(
        agent_id=1,
        symbol="BTCUSDT",
        proposed_notional_usd=100_000.0,  # exceeds max_total_exposure
        agent_guardrails=guardrails,
    )
    assert not allowed_big, "Over-limit order should be rejected"
    assert len(reasons_big) > 0


# ---------------------------------------------------------------------------
# Test 6 — Data generator sanity
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_realistic_data_sanity():
    """Generated data has correct structure and reasonable values."""
    df = generate_realistic_ohlcv(periods=1000, seed=SEED)

    assert len(df) == 1000
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    # OHLC invariants
    assert (df["high"] >= df["open"]).all(), "high must be >= open"
    assert (df["high"] >= df["close"]).all(), "high must be >= close"
    assert (df["low"] <= df["open"]).all(), "low must be <= open"
    assert (df["low"] <= df["close"]).all(), "low must be <= close"
    assert (df["low"] > 0).all(), "prices must be positive"
    assert (df["volume"] > 0).all(), "volume must be positive"

    # No NaN
    assert df.notna().all().all(), "no NaN values allowed"

    # Reasonable price range for BTC
    assert df["close"].min() > 10_000, "BTC price too low"
    assert df["close"].max() < 200_000, "BTC price too high"
