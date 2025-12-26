from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import polars as pl

from strategies.alpha_logic import VolatilityBreakoutStrategy


def _load_history(data_path: str) -> pl.DataFrame:
    # Expect columns: timestamp, open, high, low, close, volume
    try:
        return pl.read_csv(data_path)
    except Exception:
        dates = pl.datetime_range(
            start=datetime(2023, 1, 1),
            end=datetime(2024, 1, 1),
            interval="1h",
            eager=True,
        )
        return pl.DataFrame(
            {
                "timestamp": dates,
                "open": np.random.normal(100, 5, len(dates)),
                "high": np.random.normal(105, 5, len(dates)),
                "low": np.random.normal(95, 5, len(dates)),
                "close": np.random.normal(100, 5, len(dates)),
                "volume": np.random.normal(1000, 100, len(dates)),
            }
        )


def _normalize_history(df: pl.DataFrame) -> pl.DataFrame:
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Backtest history missing columns: {', '.join(missing)}")

    ts_col = df["timestamp"]
    if ts_col.dtype == pl.Utf8:
        df = df.with_columns(
            pl.col("timestamp")
            .str.strptime(pl.Datetime, strict=False)
            .alias("timestamp")
        )

    return (
        df.select(required)
        .with_columns(pl.col("timestamp").cast(pl.Datetime))
        .sort("timestamp")
        .drop_nulls(["timestamp", "open", "high", "low", "close", "volume"])
    )


def _infer_date_range(df: pl.DataFrame) -> Tuple[str, str]:
    if df.height == 0:
        return "2023-01-01", "2024-01-01"

    start_ts = df["timestamp"][0]
    end_ts = df["timestamp"][-1]
    if isinstance(start_ts, datetime) and isinstance(end_ts, datetime):
        return start_ts.isoformat(), end_ts.isoformat()
    return "2023-01-01", "2024-01-01"


def _estimate_periods_per_year(df: pl.DataFrame) -> Optional[float]:
    if df.height < 3:
        return None

    timestamps: List[datetime] = [
        ts for ts in df["timestamp"].to_list() if isinstance(ts, datetime)
    ]
    if len(timestamps) < 3:
        return None

    deltas = [
        (b - a).total_seconds()
        for a, b in zip(timestamps, timestamps[1:], strict=False)
        if isinstance(a, datetime) and isinstance(b, datetime) and b > a
    ]
    if not deltas:
        return None

    median_delta = float(np.median(np.array(deltas, dtype=float)))
    if median_delta <= 0:
        return None

    seconds_per_year = 365.0 * 24.0 * 3600.0
    return seconds_per_year / median_delta


async def run_backtest(
    strategy: VolatilityBreakoutStrategy,
    data_path: str = "data/historical.csv",
    *,
    symbol: str = "BTC/USDT",
) -> Dict[str, Any]:
    """
    Backtest the (JSON-backed) VolatilityBreakoutStrategy on local CSV history.

    Returns a superset of the DynamicStrategyEngine metrics plus a derived
    sharpe_ratio and equity_curve_array for backwards compatibility.
    """

    df = _normalize_history(_load_history(data_path))
    start_date, end_date = _infer_date_range(df)

    if df.height == 0:
        return {
            "pnl": 0.0,
            "trades": 0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "equity_curve": [],
            "sharpe_ratio": 0.0,
            "equity_curve_array": [],
        }

    strategy_config = strategy.strategy.as_dict()
    metrics = await strategy.engine.run_backtest(
        strategy_config,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        data=df,
    )

    equity_values = np.array(
        [pt.get("equity", 0.0) for pt in metrics.get("equity_curve", [])], dtype=float
    )
    sharpe_ratio = 0.0
    if equity_values.size >= 3 and np.all(np.isfinite(equity_values)):
        prev = equity_values[:-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = np.diff(equity_values) / prev
        returns = returns[np.isfinite(returns)]
        periods_per_year = _estimate_periods_per_year(df)
        annualization = (
            float(np.sqrt(periods_per_year))
            if periods_per_year
            else float(np.sqrt(max(len(returns), 1)))
        )
        if returns.size > 1 and float(np.std(returns)) != 0.0:
            sharpe_ratio = float(np.mean(returns) / np.std(returns) * annualization)

    metrics["sharpe_ratio"] = float(sharpe_ratio)
    metrics["equity_curve_array"] = equity_values.tolist()
    return metrics
