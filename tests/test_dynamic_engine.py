import sys
import os
import asyncio
import asyncio
from pathlib import Path

import numpy as np
import polars as pl
import sys

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.strategies.dynamic_engine import DynamicStrategyEngine  # noqa: E402


async def test_engine():
    engine = DynamicStrategyEngine()

    dates = pl.datetime_range(start="2023-01-01", end="2023-01-02", interval="5m", eager=True)
    df = pl.DataFrame(
        {
            "timestamp": dates,
            "open": np.random.randn(len(dates)) + 100,
            "high": np.random.randn(len(dates)) + 105,
            "low": np.random.randn(len(dates)) + 95,
            "close": np.random.randn(len(dates)) + 100,
            "volume": np.random.randint(100, 1000, len(dates)),
        }
    )

    strategy = {
        "name": "Test Strategy",
        "triggers": [
            {"indicator": "rsi", "timeframe": "5m", "operator": "<", "value": 70},
            {"indicator": "wavetrend_dot", "timeframe": "5m", "operator": "==", "value": "GREEN"},
        ],
        "logic": "AND",
        "risk": {"initial_capital": 10_000, "risk_per_trade_pct": 1, "stop_loss_pct": 1, "take_profit_pct": 2},
    }

    result = await engine.run_backtest(strategy, "BTC/USDT", "2023-01-01", "2023-01-02", data=df)
    assert result["trades"] >= 0
    assert "pnl" in result


if __name__ == "__main__":
    asyncio.run(test_engine())
