#!/usr/bin/env python3
"""
Fetch OHLCV history for a small symbol universe and store under data/history/.

This script only calls public market data endpoints and is safe for unattended
use. It delegates fetching/merging to tools/fetch_history.py.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

import pandas as pd

# Allow running from repo root or tools/
sys.path.insert(0, str(Path(__file__).parent))
from fetch_history import FetchConfig, run_fetch  # type: ignore

DEFAULT_SYMBOLS = ["SOLUSDT", "BTCUSDT", "ETHUSDT"]
DEFAULT_START = "2023-01-01"
DEFAULT_END = "2023-12-31"
DEFAULT_INTERVAL = "5"


def month_chunks(start: str, end: str) -> List[Tuple[str, str]]:
    """
    Generate inclusive monthly (start, end) tuples between two dates.
    """
    start_dt = pd.to_datetime(start).normalize()
    end_dt = pd.to_datetime(end).normalize()
    if end_dt < start_dt:
        raise ValueError("end date must be on/after start date")

    chunks: List[Tuple[str, str]] = []
    cursor = start_dt.replace(day=1)
    while cursor <= end_dt:
        chunk_start = max(cursor, start_dt)
        month_end = (cursor + pd.offsets.MonthEnd(0)).normalize()
        chunk_end = min(month_end, end_dt)
        chunks.append((chunk_start.date().isoformat(), chunk_end.date().isoformat()))
        cursor = (cursor + pd.offsets.MonthBegin(1)).normalize()
    return chunks


async def fetch_all(
    symbols: Iterable[str],
    *,
    start: str,
    end: str,
    interval: str,
    base_url: str | None,
    testnet: bool,
    limit: int,
    sleep_seconds: float,
) -> List[Path]:
    outputs: List[Path] = []
    stats: List[dict] = []
    for symbol in symbols:
        output = Path("data/history") / f"{symbol}_{interval}m.csv"
        before_rows = 0
        if output.exists():
            try:
                before_rows = len(pd.read_csv(output))
            except Exception:
                before_rows = 0
        cfg = FetchConfig(
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            output=output,
            base_url=base_url,
            testnet=testnet,
            limit=limit,
            sleep_seconds=sleep_seconds,
        )
        try:
            path = await run_fetch(cfg)
            outputs.append(path)
            try:
                df = pd.read_csv(path)
                stats.append(
                    {
                        "symbol": symbol,
                        "before": before_rows,
                        "after": len(df),
                        "added": len(df) - before_rows,
                        "start": df["timestamp"].min() if not df.empty else None,
                        "end": df["timestamp"].max() if not df.empty else None,
                    }
                )
            except Exception as exc:
                logging.warning("Failed to summarise %s: %s", symbol, exc)
        except Exception as exc:
            logging.error("Failed to fetch %s: %s", symbol, exc)
            continue
    if stats:
        for entry in stats:
            logging.info(
                "Summary %s: rows=%s (added %s) range=%s -> %s",
                entry["symbol"],
                entry["after"],
                entry["added"],
                entry.get("start"),
                entry.get("end"),
            )
    return outputs


async def fetch_all_monthly(
    symbols: Iterable[str],
    *,
    start: str,
    end: str,
    interval: str,
    base_url: str | None,
    testnet: bool,
    limit: int,
    sleep_seconds: float,
) -> tuple[List[Path], List[dict]]:
    chunks = month_chunks(start, end)
    logging.info(
        "Running monthly fetch across %d chunk(s): %s",
        len(chunks),
        "; ".join(f"{a}->{b}" for a, b in chunks),
    )

    outputs: List[Path] = []
    current_rows = {}
    for symbol in symbols:
        output = Path("data/history") / f"{symbol}_{interval}m.csv"
        rows = 0
        if output.exists():
            try:
                rows = len(pd.read_csv(output))
            except Exception:
                rows = 0
        current_rows[symbol] = rows

    for chunk_start, chunk_end in chunks:
        logging.info("Chunk %s -> %s", chunk_start, chunk_end)
        for symbol in symbols:
            output = Path("data/history") / f"{symbol}_{interval}m.csv"
            cfg = FetchConfig(
                symbol=symbol,
                interval=interval,
                start=chunk_start,
                end=chunk_end,
                output=output,
                base_url=base_url,
                testnet=testnet,
                limit=limit,
                sleep_seconds=sleep_seconds,
            )
            before_rows = current_rows.get(symbol, 0)
            try:
                path = await run_fetch(cfg)
            except Exception as exc:
                logging.warning(
                    "Chunk fetch failed for %s (%s -> %s): %s",
                    symbol,
                    chunk_start,
                    chunk_end,
                    exc,
                )
                continue

            if path not in outputs:
                outputs.append(path)
            try:
                after_rows = len(pd.read_csv(path)) if path.exists() else 0
            except Exception:
                after_rows = before_rows
            added = max(0, after_rows - before_rows)
            current_rows[symbol] = after_rows
            logging.info(
                "Chunk summary %s: rows %d -> %d (added %d)",
                symbol,
                before_rows,
                after_rows,
                added,
            )

    coverage: List[dict] = []
    for symbol in symbols:
        path = Path("data/history") / f"{symbol}_{interval}m.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
            coverage.append(
                {
                    "symbol": symbol,
                    "rows": len(df),
                    "start": df["timestamp"].min() if not df.empty else None,
                    "end": df["timestamp"].max() if not df.empty else None,
                }
            )
        except Exception as exc:
            logging.warning(
                "Failed to summarise final coverage for %s: %s", symbol, exc
            )

    return outputs, coverage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch OHLCV history for multiple symbols."
    )
    parser.add_argument(
        "--symbols", help="Comma-separated symbols, default SOLUSDT,BTCUSDT,ETHUSDT."
    )
    parser.add_argument("--start", default=DEFAULT_START, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=DEFAULT_END, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--interval", default=DEFAULT_INTERVAL, help="Interval in minutes (e.g. 5)"
    )
    parser.add_argument("--base-url", help="Override Zoomex base URL (optional).")
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use Zoomex testnet base URL when not overriding.",
    )
    parser.add_argument(
        "--limit", type=int, default=1000, help="Page size for kline requests."
    )
    parser.add_argument(
        "--sleep", type=float, default=0.25, help="Sleep between requests (seconds)."
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
    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else DEFAULT_SYMBOLS
    )
    logging.info(
        "Fetching symbols %s from %s to %s (interval %s)",
        ",".join(symbols),
        args.start,
        args.end,
        args.interval,
    )
    outputs, coverage = asyncio.run(
        fetch_all_monthly(
            symbols,
            start=args.start,
            end=args.end,
            interval=args.interval,
            base_url=args.base_url,
            testnet=args.testnet,
            limit=args.limit,
            sleep_seconds=args.sleep,
        )
    )
    if outputs:
        logging.info(
            "Fetched %d files: %s", len(outputs), ", ".join(str(p) for p in outputs)
        )
    else:
        logging.warning("No files fetched; see logs for details.")
    if coverage:
        for entry in coverage:
            logging.info(
                "Coverage %s: rows=%s range=%s -> %s",
                entry["symbol"],
                entry["rows"],
                entry.get("start"),
                entry.get("end"),
            )


if __name__ == "__main__":
    main()
