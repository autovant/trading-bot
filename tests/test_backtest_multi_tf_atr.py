import numpy as np
import pandas as pd

from src.config import PerpsConfig
from tools.backtest_perps import PerpsBacktest


def _build_ltf_series() -> pd.DataFrame:
    periods = 2800  # ~233 hours to ensure HTF warmup
    idx = pd.date_range("2024-01-01", periods=periods, freq="5min", tz="UTC")
    base = 100 + np.linspace(0, 40, periods)
    oscillation = np.sin(np.linspace(0, 12, periods)) * 0.8
    prices = base + oscillation
    pullback_idx = 2500
    prices[pullback_idx - 1] += 1.0
    prices[pullback_idx] = prices[pullback_idx - 1] - 1.2  # pullback into EMA20 zone
    lift = np.linspace(0, 12, periods - pullback_idx - 1)
    prices[pullback_idx + 1 :] = prices[pullback_idx + 1 :] + lift

    high = prices + 0.6
    low = prices - 0.6

    return pd.DataFrame(
        {
            "open": prices,
            "high": high,
            "low": low,
            "close": prices,
            "volume": np.full(periods, 1500.0),
        },
        index=idx,
    )


def _build_htf_series() -> pd.DataFrame:
    periods = 300
    idx = pd.date_range("2024-01-01", periods=periods, freq="60min", tz="UTC")
    base = 90 + np.linspace(0, 80, periods)
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base,
            "volume": np.full(periods, 3000.0),
        },
        index=idx,
    )


def test_backtest_generates_trades_and_r_multiple():
    ltf_df = _build_ltf_series()
    htf_df = _build_htf_series()
    config = PerpsConfig(
        minAtrPct=0.0005,
        hardStopMinPct=0.005,
        atrStopMultiple=1.2,
        tp1Multiple=1.0,
        tp2Multiple=2.0,
        maxBarsInTrade=60,
        maxEmaDistanceAtr=1.5,
    )
    backtest = PerpsBacktest(config, initial_balance=1000.0, use_multi_tf=True)
    metrics = backtest.run_backtest(ltf_df, htf_df)

    assert metrics["total_trades"] > 0
    assert metrics["avg_r_multiple"] != 0 or metrics["median_r_multiple"] != 0
    assert metrics["tp1_hit_rate"] >= 0
    assert isinstance(metrics["tp2_hit_rate"], float)
