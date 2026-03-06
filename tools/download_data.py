"""
CLI tool for downloading historical OHLCV data.

Usage:
    python -m tools.download_data --symbol BTCUSDT --timeframe 5m --start 2024-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from tools.data_downloader import DataDownloader


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download historical OHLCV candle data from Binance"
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Trading pair symbol (e.g. BTCUSDT)",
    )
    parser.add_argument(
        "--timeframe",
        required=True,
        choices=["1m", "5m", "15m", "1h", "4h", "1d"],
        help="Candle interval",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output-dir",
        default="data/bars",
        help="Output directory for Parquet files (default: data/bars)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    downloader = DataDownloader(output_dir=args.output_dir)

    try:
        path = asyncio.run(
            downloader.download(
                symbol=args.symbol,
                timeframe=args.timeframe,
                start_date=args.start,
                end_date=args.end,
            )
        )
        print(f"Download complete: {path}")
    except Exception as exc:
        logging.getLogger(__name__).error("Download failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
