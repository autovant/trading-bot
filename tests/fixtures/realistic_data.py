"""
Realistic synthetic OHLCV data generator for strategy validation tests.

Generates data with proper market microstructure: trending periods,
mean-reversion, volatility clustering (GARCH-like), and volume patterns.
All randomness is seeded for deterministic reproducibility.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


def generate_realistic_ohlcv(
    symbol: str = "BTCUSDT",
    start_date: str = "2024-01-01",
    periods: int = 4380,  # ~6 months of 1h bars
    freq: str = "1h",
    base_price: float = 42_000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic OHLCV data with market microstructure.

    Features:
    - Regime changes (trending / mean-reverting / consolidation)
    - Volatility clustering (GARCH-like)
    - Volume patterns correlated with volatility
    - Proper OHLC relationships (high >= open,close; low <= open,close)
    """
    rng = np.random.default_rng(seed)

    # --- Regime schedule ---
    # Split data into segments with different drift characteristics
    regime_len = periods // 6
    regimes = []
    for i in range(6):
        kind = rng.choice(["trend_up", "trend_down", "consolidation"], p=[0.35, 0.30, 0.35])
        regimes.extend([kind] * regime_len)
    # Pad any remainder
    regimes.extend([regimes[-1]] * (periods - len(regimes)))

    drift_map = {"trend_up": 0.0003, "trend_down": -0.0003, "consolidation": 0.0}

    # --- GARCH-like volatility clustering ---
    base_vol = 0.008  # base hourly vol for BTC
    vol = np.empty(periods)
    vol[0] = base_vol
    alpha, beta = 0.10, 0.85
    omega = base_vol**2 * (1 - alpha - beta)
    for t in range(1, periods):
        shock = rng.standard_normal()
        vol[t] = np.sqrt(omega + alpha * (vol[t - 1] * shock) ** 2 + beta * vol[t - 1] ** 2)
        vol[t] = max(vol[t], base_vol * 0.3)  # floor

    # --- Price path ---
    log_returns = np.empty(periods)
    for t in range(periods):
        drift = drift_map[regimes[t]]
        log_returns[t] = drift + vol[t] * rng.standard_normal()

    log_prices = np.log(base_price) + np.cumsum(log_returns)
    close_prices = np.exp(log_prices)

    # --- OHLC from close ---
    open_prices = np.empty(periods)
    open_prices[0] = base_price
    open_prices[1:] = close_prices[:-1]

    # Intrabar high/low as a spread around max/min of open,close
    spread_factor = vol * rng.uniform(0.3, 1.5, periods)
    high_prices = np.maximum(open_prices, close_prices) * (1 + np.abs(spread_factor))
    low_prices = np.minimum(open_prices, close_prices) * (1 - np.abs(spread_factor))
    low_prices = np.maximum(low_prices, 1.0)  # no negative prices

    # --- Volume: correlated with volatility + random noise ---
    base_volume = 500.0
    volume = base_volume * (1 + 10 * vol / base_vol) * rng.uniform(0.5, 1.5, periods)

    # --- Build DataFrame ---
    timestamps = pd.date_range(start=start_date, periods=periods, freq=freq, tz="UTC")

    df = pd.DataFrame(
        {
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "volume": volume,
        },
        index=timestamps,
    )
    df.index.name = "timestamp"
    return df


def generate_multi_timeframe_data(
    symbol: str = "BTCUSDT",
    start_date: str = "2024-01-01",
    months: int = 6,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Generate aligned 1h, 4h, and 1d data from a single 1h series.

    Returns a dict keyed by the config timeframe names:
    ``{"signal": 1h_df, "setup": 4h_df, "regime": 1d_df}``
    """
    hours = months * 30 * 24  # approximate
    hourly = generate_realistic_ohlcv(
        symbol=symbol,
        start_date=start_date,
        periods=hours,
        freq="1h",
        seed=seed,
    )

    def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        return (
            df.resample(rule)
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
        )

    four_hour = resample(hourly, "4h")
    daily = resample(hourly, "1D")

    return {
        "signal": hourly,
        "setup": four_hour,
        "regime": daily,
    }
