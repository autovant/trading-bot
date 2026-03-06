#!/usr/bin/env python3
"""
Fetch OHLCV history via CCXT from any accessible exchange.

Tries exchanges in order until one works. Outputs Parquet files compatible
with the replay service (parquet://bars/).

Usage:
    python tools/fetch_ccxt_history.py --symbol BTCUSDT --start 2023-01-01 --end 2024-12-31
    python tools/fetch_ccxt_history.py --all  # fetches default universe
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Exchanges to try in priority order (publicly accessible, no auth needed for OHLCV)
EXCHANGE_PRIORITY = ["okx", "bitget", "gate", "kraken"]

DEFAULT_SYMBOLS = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]
DEFAULT_INTERVAL = "5m"
DEFAULT_START = "2023-01-01"
DEFAULT_END = "2024-12-31"
OUTPUT_DIR = Path("data/history")
BARS_DIR = Path("sample_data")  # For replay service


def _normalize_symbol(symbol: str, exchange_id: str) -> str:
    """Convert BTCUSDT-style to BTC/USDT for CCXT."""
    # Common patterns
    for quote in ["USDT", "USDC", "USD", "BTC", "ETH"]:
        if symbol.upper().endswith(quote) and len(symbol) > len(quote):
            base = symbol[: -len(quote)]
            return f"{base}/{quote}"
    return symbol


def _get_exchange() -> ccxt.Exchange:
    """Try exchanges until one is accessible."""
    for name in EXCHANGE_PRIORITY:
        try:
            ex = getattr(ccxt, name)({"enableRateLimit": True})
            ex.load_markets()
            logger.info("Using exchange: %s", name)
            return ex
        except Exception as e:
            logger.warning("Exchange %s unavailable: %s", name, e)
    raise RuntimeError(f"No accessible exchange found (tried {EXCHANGE_PRIORITY})")


def fetch_ohlcv(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch OHLCV data in batches, respecting rate limits."""
    ccxt_symbol = _normalize_symbol(symbol, exchange.id)

    if ccxt_symbol not in exchange.markets:
        logger.warning("Symbol %s not found on %s, trying alternatives", ccxt_symbol, exchange.id)
        # Try linear perp symbol
        alt = f"{ccxt_symbol}:USDT"
        if alt in exchange.markets:
            ccxt_symbol = alt
        else:
            raise ValueError(f"Symbol {symbol} ({ccxt_symbol}) not available on {exchange.id}")

    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)

    all_candles = []
    since = start_ts
    limit = 500  # Conservative batch size

    while since < end_ts:
        try:
            candles = exchange.fetch_ohlcv(ccxt_symbol, timeframe, since=since, limit=limit)
        except Exception as e:
            logger.error("Fetch error at %s: %s", datetime.fromtimestamp(since / 1000, tz=timezone.utc), e)
            break

        if not candles:
            break

        all_candles.extend(candles)
        last_ts = candles[-1][0]

        if last_ts <= since:
            break
        since = last_ts + 1

        logger.info(
            "Fetched %d candles for %s (up to %s)",
            len(all_candles),
            symbol,
            datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
        )

        # Rate limit
        time.sleep(exchange.rateLimit / 1000)

    if not all_candles:
        logger.warning("No data fetched for %s", symbol)
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df[(df["timestamp"] >= pd.Timestamp(start_date, tz="UTC")) & (df["timestamp"] <= pd.Timestamp(end_date, tz="UTC"))]
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df["symbol"] = symbol

    logger.info("Total: %d candles for %s (%s to %s)", len(df), symbol, df["timestamp"].min(), df["timestamp"].max())
    return df


def save_data(df: pd.DataFrame, symbol: str, output_dir: Path, bars_dir: Path, interval: str = "1h") -> None:
    """Save as both CSV (data/history/) and Parquet (sample_data/ for replay)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    bars_dir.mkdir(parents=True, exist_ok=True)

    # Include interval in filename (e.g., BTCUSDT_5m.csv) for sweep tool compatibility
    csv_path = output_dir / f"{symbol}_{interval}.csv"
    df.to_csv(csv_path, index=False)
    logger.info("Saved CSV: %s (%d rows)", csv_path, len(df))

    parquet_path = bars_dir / f"{symbol}_{interval}.parquet"
    df.to_parquet(parquet_path, index=False)
    logger.info("Saved Parquet: %s (%d rows)", parquet_path, len(df))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch OHLCV history via CCXT")
    parser.add_argument("--symbol", type=str, help="Trading pair (e.g. BTCUSDT)")
    parser.add_argument("--all", action="store_true", help="Fetch default universe")
    parser.add_argument("--start", type=str, default=DEFAULT_START, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=DEFAULT_END, help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", type=str, default=DEFAULT_INTERVAL, help="Candle interval (1h, 4h, 1d)")
    parser.add_argument("--output", type=str, default=str(OUTPUT_DIR), help="Output directory")
    parser.add_argument("--exchange", type=str, help="Force specific exchange")
    args = parser.parse_args()

    symbols = DEFAULT_SYMBOLS if args.all else [args.symbol or "BTCUSDT"]
    output_dir = Path(args.output)

    if args.exchange:
        exchange = getattr(ccxt, args.exchange)({"enableRateLimit": True})
        exchange.load_markets()
    else:
        exchange = _get_exchange()

    for symbol in symbols:
        try:
            df = fetch_ohlcv(exchange, symbol, args.interval, args.start, args.end)
            if not df.empty:
                save_data(df, symbol, output_dir, BARS_DIR, interval=args.interval)
            else:
                logger.warning("Skipping %s — no data", symbol)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", symbol, e)

    logger.info("Done. Fetched data for %d symbols.", len(symbols))


if __name__ == "__main__":
    main()
