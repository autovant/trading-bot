#!/usr/bin/env python3
"""
Download Zoomex public OHLCV history to CSV for backtesting.

This script only hits public market data endpoints; it never places or signs
orders. Output CSVs are compatible with tools/backtest_perps.py and the
CSVDataProvider.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import gzip
import io

import pandas as pd
from aiohttp import ClientSession, ClientTimeout

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.exchanges.zoomex_v3 import ZoomexV3Client, ZoomexError  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 1000  # per Zoomex kline docs
DEFAULT_SLEEP_SECONDS = 0.25


@dataclass
class FetchConfig:
    symbol: str
    interval: str
    start: str
    end: str
    output: Path
    base_url: Optional[str] = None
    testnet: bool = False
    limit: int = DEFAULT_LIMIT
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS
    max_retries: int = 3


def _to_ms(dt_str: str) -> int:
    ts = pd.to_datetime(dt_str, utc=True)
    return int(ts.timestamp() * 1000)


def _interval_ms(interval: str) -> int:
    try:
        minutes = int(interval)
        return minutes * 60 * 1000
    except ValueError:
        raise ValueError(f"Interval must be numeric minutes for CSV output, got {interval}")


def _resolve_base_url(base_url: Optional[str], testnet: bool) -> str:
    if base_url:
        return base_url
    if testnet:
        return "https://openapi-testnet.zoomex.com"
    return os.getenv("ZOOMEX_BASE", "https://openapi.zoomex.com")


async def _download_public_dataset_history(config: FetchConfig, base_url: str) -> pd.DataFrame:
    """
    Fallback path for public Bybit/Zoomex-compatible datasets hosted at public.bybit.com.
    Files are organised as:
    {base}/{SYMBOL}/{YEAR}/{SYMBOL}_{INTERVAL}_{YYYY-MM-DD}_{YYYY-MM-DD}.csv.gz
    """
    start_dt = pd.to_datetime(config.start, utc=True)
    end_dt = pd.to_datetime(config.end, utc=True)
    base = base_url.rstrip("/")
    try:
        int(config.interval)
    except ValueError:
        raise ValueError("Interval must be numeric minutes for public dataset downloads.")

    def _month_chunks() -> List[tuple[pd.Timestamp, pd.Timestamp]]:
        cursor = start_dt.normalize().replace(day=1)
        chunks: List[tuple[pd.Timestamp, pd.Timestamp]] = []
        while cursor <= end_dt:
            month_end = (cursor + pd.offsets.MonthEnd(0)).normalize()
            chunks.append((cursor, month_end))
            cursor = (cursor + pd.offsets.MonthBegin(1)).normalize()
        return chunks

    async with ClientSession() as session:
        batches: List[pd.DataFrame] = []
        for chunk_start, chunk_end in _month_chunks():
            year = chunk_start.year
            fname = f"{config.symbol}_{config.interval}_{chunk_start.date()}_{chunk_end.date()}.csv.gz"
            url = f"{base}/{config.symbol}/{year}/{fname}"
            try:
                async with session.get(url, timeout=ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning("Public dataset fetch failed (%s): HTTP %s", url, resp.status)
                        continue
                    raw = await resp.read()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Request error for %s: %s", url, exc)
                continue

            try:
                decompressed = gzip.decompress(raw)
                df = pd.read_csv(
                    io.BytesIO(decompressed),
                    header=None,
                    names=["timestamp", "open", "high", "low", "close", "volume"],
                )
                df["timestamp"] = pd.to_datetime(
                    df["timestamp"], format="%Y.%m.%d %H:%M", utc=True, errors="coerce"
                )
                df.dropna(subset=["timestamp"], inplace=True)
                df = df[(df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)]
                numeric_cols = ["open", "high", "low", "close", "volume"]
                df[numeric_cols] = df[numeric_cols].astype(float)
                if df.empty:
                    logger.warning("No rows after filtering for %s (%s to %s)", url, start_dt, end_dt)
                    continue
                batches.append(df)
                logger.info(
                    "Fetched %d rows from %s (range %s to %s)",
                    len(df),
                    url,
                    df["timestamp"].min(),
                    df["timestamp"].max(),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to parse %s: %s", url, exc)
                continue

    if not batches:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    merged = pd.concat(batches).sort_values("timestamp")
    merged = merged.drop_duplicates(subset=["timestamp"], keep="first")
    merged["timestamp"] = merged["timestamp"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = merged[["timestamp", "open", "high", "low", "close", "volume"]]
    return merged


async def _fetch_batch(
    client: ZoomexV3Client,
    *,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int,
) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
        "start": start_ms,
        "end": end_ms,
    }
    try:
        return await client.get_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            start=start_ms,
            end=end_ms,
        )
    except ZoomexError as exc:
        logger.error(
            "History fetch failed against %s (params=%s): %s",
            client.base_url,
            params,
            exc,
        )
        raise


async def download_history(config: FetchConfig) -> pd.DataFrame:
    start_ms = _to_ms(config.start)
    end_ms = _to_ms(config.end)
    interval_ms = _interval_ms(config.interval)
    base_url = _resolve_base_url(config.base_url, config.testnet)

    if "public.bybit.com" in base_url:
        logger.info("Using public dataset base %s for %s %sm.", base_url, config.symbol, config.interval)
        return await _download_public_dataset_history(config, base_url)

    async with ClientSession() as session:
        client = ZoomexV3Client(
            session,
            base_url=base_url,
            category="linear",
            require_auth=False,
            max_retries=config.max_retries,
            mode_name="testnet" if config.testnet else "history",
        )

        batches: List[pd.DataFrame] = []
        cursor = start_ms
        start_dt = pd.to_datetime(config.start, utc=True)
        end_dt = pd.to_datetime(config.end, utc=True)
        logger.info(
            "Starting fetch for %s %sm from %s to %s using %s",
            config.symbol,
            config.interval,
            start_dt,
            end_dt,
            base_url,
        )

        while cursor <= end_ms:
            try:
                df = await _fetch_batch(
                    client,
                    symbol=config.symbol,
                    interval=config.interval,
                    start_ms=cursor,
                    end_ms=end_ms,
                    limit=config.limit,
                )
            except ZoomexError as exc:
                logger.error(
                    "Kline fetch aborted for %s: %s", config.symbol, exc
                )
                break

            if df.empty:
                logger.warning(
                    "No data returned for %s at %s (end=%s).",
                    config.symbol,
                    datetime.fromtimestamp(cursor / 1000, tz=timezone.utc),
                    datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc),
                )
                break

            df = df[(df.index >= start_dt) & (df.index <= end_dt)]
            batches.append(df)

            last_timestamp = df.index.max()
            last_index_ms = int(last_timestamp.timestamp() * 1000)
            next_cursor = last_index_ms + interval_ms
            if next_cursor <= cursor:
                logger.warning("Pagination stalled (cursor %s, next %s); stopping to avoid loop.", cursor, next_cursor)
                break
            cursor = next_cursor
            await asyncio.sleep(config.sleep_seconds)

    if not batches:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    merged = pd.concat(batches).sort_index()
    merged = merged[~merged.index.duplicated(keep="first")]

    merged.reset_index(inplace=True)
    merged.rename(columns={"start": "timestamp"}, inplace=True)
    merged["timestamp"] = merged["timestamp"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = merged[["timestamp", "open", "high", "low", "close", "volume"]]
    return merged


def _parse_timestamp(series: pd.Series) -> pd.Series:
    """
    Normalize timestamp values that may be ISO8601 strings or millisecond epochs.
    """
    parsed = pd.to_datetime(series, utc=True, errors="coerce")
    needs_ms = parsed.isna()
    if needs_ms.any():
        parsed_ms = pd.to_datetime(series, utc=True, errors="coerce", unit="ms")
        parsed = parsed.fillna(parsed_ms)
    return parsed


def _merge_existing(output: Path, fresh: pd.DataFrame) -> pd.DataFrame:
    if not output.exists():
        return fresh

    existing = pd.read_csv(output)
    if "timestamp" not in existing.columns:
        raise ValueError(f"Existing CSV at {output} is missing 'timestamp' column")

    combined = pd.concat([existing, fresh], ignore_index=True)
    combined["timestamp"] = _parse_timestamp(combined["timestamp"])
    combined = combined[combined["timestamp"].notna()]
    combined = combined[combined["timestamp"] >= pd.Timestamp("2018-01-01", tz="UTC")]
    combined.sort_values("timestamp", inplace=True)
    combined = combined.drop_duplicates(subset=["timestamp"], keep="first")
    combined["timestamp"] = combined["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return combined


async def run_fetch(config: FetchConfig) -> Path:
    resolved_base = _resolve_base_url(config.base_url, config.testnet)
    config.base_url = resolved_base
    logger.info(
        "Fetching %s %s-minute klines from %s to %s (base_url=%s testnet=%s)",
        config.symbol,
        config.interval,
        config.start,
        config.end,
        resolved_base,
        config.testnet,
    )
    fresh = await download_history(config)
    if fresh.empty:
        raise RuntimeError("No data downloaded; check symbol, interval, or date range.")

    output_dir = config.output.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    existed = config.output.exists()
    existing_rows = 0
    if existed:
        try:
            existing_rows = len(pd.read_csv(config.output))
        except Exception:
            existing_rows = 0
    merged = _merge_existing(config.output, fresh)
    merged.to_csv(config.output, index=False)
    action = "Appended" if existed else "Created"
    added = len(merged) - existing_rows if existed else len(merged)
    logger.info(
        "%s %s (%d total rows, %d new).",
        action,
        config.output,
        len(merged),
        added,
    )
    return config.output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Zoomex OHLCV history to CSV.")
    parser.add_argument("--symbol", required=True, help="Symbol, e.g. SOLUSDT")
    parser.add_argument("--interval", default="5", help="Interval in minutes (e.g. 5)")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--output",
        help="Output CSV path (default: data/history/{SYMBOL}_{INTERVAL}m.csv)",
    )
    parser.add_argument(
        "--base-url",
        help="Override base URL for Zoomex API (defaults to ZOOMEX_BASE or production).",
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use the Zoomex testnet base URL (ignored if --base-url is provided).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Page size for kline requests (default 1000).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Sleep between requests to respect rate limits (seconds).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    output = (
        Path(args.output)
        if args.output
        else Path("data/history") / f"{args.symbol}_{args.interval}m.csv"
    )
    config = FetchConfig(
        symbol=args.symbol,
        interval=args.interval,
        start=args.start,
        end=args.end,
        output=output,
        base_url=args.base_url,
        testnet=args.testnet,
        limit=args.limit,
        sleep_seconds=args.sleep,
    )
    try:
        asyncio.run(run_fetch(config))
    except Exception as exc:
        logger.error("Fetch failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
