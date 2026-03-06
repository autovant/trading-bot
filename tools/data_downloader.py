"""
Bulk OHLCV historical data downloader from Binance public API.

Downloads candle data in paginated batches and writes to Parquet files
compatible with the replay service format.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

VALID_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}

# Max candles returned per Binance request
BATCH_SIZE = 1000

# Minimum delay between requests (seconds)
REQUEST_DELAY = 0.1

# Retry config
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0


class DataDownloader:
    """Downloads historical OHLCV data from Binance and saves as Parquet."""

    def __init__(self, output_dir: str = "data/bars") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def download(
        self,
        symbol: str,
        timeframe: str,
        start_date: str,
        end_date: str,
        source: str = "binance",
    ) -> str:
        """
        Download OHLCV data in paginated batches.

        Args:
            symbol: Trading pair (e.g. BTCUSDT).
            timeframe: Candle interval (1m, 5m, 15m, 1h, 4h, 1d).
            start_date: ISO date string (YYYY-MM-DD).
            end_date: ISO date string (YYYY-MM-DD).
            source: Data source (only "binance" supported).

        Returns:
            Path to the output Parquet file.
        """
        if source != "binance":
            raise ValueError(f"Unsupported data source: {source}")

        if timeframe not in VALID_INTERVALS:
            raise ValueError(
                f"Invalid timeframe '{timeframe}'. Must be one of {VALID_INTERVALS}"
            )

        start_ms = self._date_to_ms(start_date)
        end_ms = self._date_to_ms(end_date)

        if start_ms >= end_ms:
            raise ValueError("start_date must be before end_date")

        logger.info(
            "Starting download: %s %s from %s to %s",
            symbol,
            timeframe,
            start_date,
            end_date,
        )

        rows = await self._binance_klines(symbol, timeframe, start_ms, end_ms)

        if not rows:
            raise RuntimeError(
                f"No data returned for {symbol} {timeframe} "
                f"({start_date} to {end_date})"
            )

        df = pd.DataFrame(rows)
        df = df.astype(
            {
                "timestamp": "int64",
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
            }
        )
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

        output_path = self.output_dir / f"{symbol}_{timeframe}.parquet"
        df.to_parquet(output_path, index=False, engine="pyarrow")

        logger.info(
            "Saved %d candles to %s",
            len(df),
            output_path,
        )
        return str(output_path)

    async def _binance_klines(
        self, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> List[dict]:
        """Fetch klines from Binance REST API with pagination and rate limiting."""
        all_rows: List[dict] = []
        cursor = start_ms

        async with httpx.AsyncClient(timeout=30.0) as client:
            while cursor < end_ms:
                params = {
                    "symbol": symbol.upper(),
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": BATCH_SIZE,
                }

                data = await self._request_with_retry(client, params)

                if not data:
                    break

                for kline in data:
                    all_rows.append(
                        {
                            "timestamp": int(kline[0]),
                            "open": float(kline[1]),
                            "high": float(kline[2]),
                            "low": float(kline[3]),
                            "close": float(kline[4]),
                            "volume": float(kline[5]),
                        }
                    )

                # Move cursor past the last candle's open time
                cursor = int(data[-1][0]) + 1

                logger.info(
                    "Downloaded %d candles for %s %s",
                    len(all_rows),
                    symbol,
                    interval,
                )

                await asyncio.sleep(REQUEST_DELAY)

        return all_rows

    async def _request_with_retry(
        self, client: httpx.AsyncClient, params: dict
    ) -> list:
        """Execute a single klines request with retry on transient errors."""
        backoff = INITIAL_BACKOFF

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.get(BINANCE_KLINES_URL, params=params)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", str(backoff)))
                    logger.warning(
                        "Rate limited (429). Waiting %ds (attempt %d/%d)",
                        retry_after,
                        attempt,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(retry_after)
                    backoff *= 2
                    continue

                if resp.status_code >= 500:
                    logger.warning(
                        "Server error %d. Retrying in %.1fs (attempt %d/%d)",
                        resp.status_code,
                        backoff,
                        attempt,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue

                resp.raise_for_status()
                return resp.json()

            except httpx.TimeoutException:
                logger.warning(
                    "Request timeout. Retrying in %.1fs (attempt %d/%d)",
                    backoff,
                    attempt,
                    MAX_RETRIES,
                )
                await asyncio.sleep(backoff)
                backoff *= 2

        raise RuntimeError(
            f"Failed to fetch klines after {MAX_RETRIES} retries "
            f"(symbol={params.get('symbol')}, startTime={params.get('startTime')})"
        )

    @staticmethod
    def _date_to_ms(date_str: str) -> int:
        """Convert YYYY-MM-DD string to epoch milliseconds (UTC)."""
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
