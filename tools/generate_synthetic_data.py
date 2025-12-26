#!/usr/bin/env python3
"""
Generate synthetic OHLCV data for backtesting.
Creates trending data with pullbacks to test the multi-timeframe ATR strategy.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def generate_data(
    symbol: str,
    interval_minutes: int,
    days: int,
    start_price: float,
    trend_slope: float,
    volatility: float,
    output_path: Path,
):
    # Create timestamp index
    freq = f"{interval_minutes}min"
    periods = int(days * 24 * 60 / interval_minutes)
    dates = pd.date_range(start="2024-01-01", periods=periods, freq=freq, tz="UTC")

    # Generate random walk with trend
    np.random.seed(42)
    steps = np.random.normal(loc=trend_slope, scale=volatility, size=periods)
    price_path = start_price + np.cumsum(steps)

    # Ensure no negative prices
    price_path = np.maximum(price_path, 1.0)

    # Create OHLCV
    data = {
        "timestamp": dates,
        "open": price_path,
        "high": price_path + np.abs(np.random.normal(0, volatility / 2, periods)),
        "low": price_path - np.abs(np.random.normal(0, volatility / 2, periods)),
        "close": price_path + np.random.normal(0, volatility / 4, periods),
        "volume": np.abs(np.random.normal(1000, 200, periods)),
    }

    df = pd.DataFrame(data)

    # Format timestamp
    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Save to CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Generated {len(df)} rows to {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SOLUSDT")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    # Generate 5m data
    generate_data(
        symbol=args.symbol,
        interval_minutes=5,
        days=args.days,
        start_price=100.0,
        trend_slope=0.05,  # Mild uptrend
        volatility=0.5,
        output_path=Path(f"data/history/{args.symbol}_5m.csv"),
    )

    # Generate 60m data (resampled from 5m would be better, but independent generation is faster for simple test)
    # We use same seed/logic but coarser steps to simulate "aligned" trends roughly
    generate_data(
        symbol=args.symbol,
        interval_minutes=60,
        days=args.days,
        start_price=100.0,
        trend_slope=0.6,  # 12x slope for 12x interval
        volatility=2.0,
        output_path=Path(f"data/history/{args.symbol}_60m.csv"),
    )


if __name__ == "__main__":
    main()
