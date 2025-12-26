"""
Integration test to validate core components work together.

This is intentionally lightweight (no external services required).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import load_config
from src.database import DatabaseManager
from src.indicators import TechnicalIndicators
from src.models import ConfidenceScore, MarketRegime, TradingSetup, TradingSignal


async def run_integration_test(db_path: str) -> None:
    config = load_config()
    assert config.trading.symbols

    db = DatabaseManager(db_path)
    await db.initialize()

    metrics = {
        "total_trades": 10,
        "winning_trades": 6,
        "losing_trades": 4,
        "total_pnl": 150.50,
        "max_drawdown": 5.2,
        "win_rate": 60.0,
        "profit_factor": 1.8,
        "sharpe_ratio": 1.2,
    }

    await db.update_performance_metrics(metrics)
    retrieved_metrics = await db.get_performance_metrics()
    assert retrieved_metrics is not None
    assert retrieved_metrics["total_trades"] == metrics["total_trades"]

    await db.close()

    dates = pd.date_range("2023-01-01", periods=100, freq="1h")
    np.random.seed(42)

    base_price = 50_000
    returns = np.random.normal(0.0001, 0.02, len(dates))
    prices = [base_price]
    for ret in returns[1:]:
        new_price = prices[-1] * (1 + ret)
        prices.append(max(new_price, base_price * 0.5))

    data = pd.DataFrame(
        {
            "open": [prices[i - 1] if i > 0 else prices[i] for i in range(len(prices))],
            "high": [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
            "low": [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
            "close": prices,
            "volume": np.random.uniform(1000, 5000, len(prices)),
        },
        index=dates,
    )

    indicators = TechnicalIndicators()
    ema_20 = indicators.ema(data["close"], 20)
    rsi = indicators.rsi(data["close"], 14)
    macd_line, macd_signal, macd_hist = indicators.macd(data["close"])
    atr = indicators.atr(data, 14)
    adx = indicators.adx(data, 14)

    assert len(ema_20) == len(data)
    assert not pd.isna(rsi.iloc[-1])
    assert not pd.isna(macd_line.iloc[-1])
    assert not pd.isna(macd_signal.iloc[-1])
    assert not pd.isna(macd_hist.iloc[-1])
    assert not pd.isna(atr.iloc[-1])
    assert not pd.isna(adx.iloc[-1])

    regime = MarketRegime(regime="bullish", strength=0.8, confidence=0.9)
    setup = TradingSetup(direction="long", quality=0.7, strength=0.8)
    signal = TradingSignal(
        signal_type="breakout",
        direction="long",
        strength=0.9,
        confidence=0.8,
        entry_price=50_000,
        stop_loss=49_000,
        take_profit=52_000,
    )
    confidence = ConfidenceScore(
        regime_score=20.0,
        setup_score=25.0,
        signal_score=30.0,
        penalty_score=-2.0,
        total_score=73.0,
    )

    assert regime.regime == "bullish"
    assert setup.direction == "long"
    assert signal.direction == "long"
    assert confidence.total_score == 73.0

    ladder_weights = config.risk_management.ladder_entries.weights
    assert abs(sum(ladder_weights) - 1.0) < 0.01


@pytest.mark.asyncio
async def test_integration(tmp_path: Path) -> None:
    await run_integration_test(str(tmp_path / "integration_test.db"))


if __name__ == "__main__":
    db_path = str(Path("data") / "integration_test.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(run_integration_test(db_path))
    except Exception as exc:
        print(f"Integration test failed: {exc}")
        sys.exit(1)
    sys.exit(0)
