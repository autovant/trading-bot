#!/usr/bin/env python3
"""
Diagnostic tool to debug backtest issues.

This script helps identify why backtests might be failing by:
- Testing data fetching
- Validating signal generation
- Checking configuration
- Verifying indicator calculations

Usage:
    python tools/diagnose_backtest.py --symbol BTCUSDT --days 30
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.exchanges.zoomex_v3 import ZoomexV3Client
from src.strategies.perps_trend_vwap import compute_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def test_data_fetch(symbol: str, interval: str, days: int, use_testnet: bool):
    """Test fetching historical data."""
    logger.info("=" * 60)
    logger.info("Testing Data Fetch")
    logger.info("=" * 60)

    base_url = (
        "https://openapi-testnet.zoomex.com"
        if use_testnet
        else "https://openapi.zoomex.com"
    )

    try:
        async with aiohttp.ClientSession() as session:
            client = ZoomexV3Client(session, base_url=base_url, category="linear", require_auth=False)

            logger.info(f"Fetching {symbol} {interval}m data...")
            df = await client.get_klines(symbol=symbol, interval=interval, limit=200)

            if df.empty:
                logger.error("❌ No data returned from API")
                return None

            logger.info(f"✅ Fetched {len(df)} candles")
            logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
            logger.info(f"   Columns: {list(df.columns)}")
            logger.info(f"   Latest close: ${df['close'].iloc[-1]:.2f}")

            return df

    except Exception as e:
        logger.error(f"❌ Data fetch failed: {e}", exc_info=True)
        return None


def test_signal_generation(df: pd.DataFrame):
    """Test signal generation on data."""
    logger.info("=" * 60)
    logger.info("Testing Signal Generation")
    logger.info("=" * 60)

    if df is None or df.empty:
        logger.error("❌ No data available for signal testing")
        return

    try:
        # Test with different window sizes
        for window_size in [35, 50, 100, len(df)]:
            if len(df) < window_size:
                continue

            window = df.iloc[-window_size:]
            signals = compute_signals(window)

            logger.info(f"\nWindow size: {window_size} candles")
            logger.info(f"  Long signal: {signals['long_signal']}")
            logger.info(f"  Price: ${signals['price']:.2f}")
            logger.info(f"  Fast MA: ${signals['fast']:.2f}")
            logger.info(f"  Slow MA: ${signals['slow']:.2f}")
            logger.info(f"  VWAP: ${signals['vwap']:.2f}")
            logger.info(f"  RSI: {signals['rsi']:.2f}")

            if signals['long_signal']:
                logger.info("  ✅ LONG SIGNAL DETECTED!")

        # Count signals over entire dataset
        signal_count = 0
        for i in range(35, len(df)):
            window = df.iloc[:i+1]
            signals = compute_signals(window)
            if signals['long_signal']:
                signal_count += 1

        logger.info(f"\n✅ Total signals in dataset: {signal_count}")

        if signal_count == 0:
            logger.warning("⚠️  No signals generated - strategy may be too strict")
            logger.info("\nPossible reasons:")
            logger.info("  1. Market conditions don't match strategy criteria")
            logger.info("  2. RSI range (30-65) is too narrow")
            logger.info("  3. MA crossover + VWAP + RSI conditions rarely align")
            logger.info("\nSuggestions:")
            logger.info("  - Try a different time period")
            logger.info("  - Adjust RSI thresholds in strategy")
            logger.info("  - Use shorter MA periods for more signals")

    except Exception as e:
        logger.error(f"❌ Signal generation failed: {e}", exc_info=True)


def test_configuration(config_path: str):
    """Test configuration loading."""
    logger.info("=" * 60)
    logger.info("Testing Configuration")
    logger.info("=" * 60)

    try:
        os.environ["CONFIG_PATH"] = config_path
        config = get_config()

        logger.info(f"✅ Config loaded from: {config_path}")
        logger.info(f"   Symbol: {config.perps.symbol}")
        logger.info(f"   Interval: {config.perps.interval}")
        logger.info(f"   Risk %: {config.perps.riskPct * 100:.2f}%")
        logger.info(f"   Stop-loss %: {config.perps.stopLossPct * 100:.2f}%")
        logger.info(f"   Take-profit %: {config.perps.takeProfitPct * 100:.2f}%")
        logger.info(f"   Max cash deploy: ${config.perps.cashDeployCap:.2f}")

        return config

    except Exception as e:
        logger.error(f"❌ Config loading failed: {e}", exc_info=True)
        return None


def test_indicators(df: pd.DataFrame):
    """Test indicator calculations."""
    logger.info("=" * 60)
    logger.info("Testing Indicators")
    logger.info("=" * 60)

    if df is None or df.empty:
        logger.error("❌ No data available for indicator testing")
        return

    try:
        from src.ta_indicators.ta_core import sma, rsi_ema, vwap

        closes = df["close"].astype(float)

        # Test SMA
        fast_ma = sma(closes, 10)
        slow_ma = sma(closes, 30)
        logger.info(f"✅ SMA(10): {fast_ma.iloc[-1]:.2f}")
        logger.info(f"✅ SMA(30): {slow_ma.iloc[-1]:.2f}")

        # Test RSI
        rsi = rsi_ema(closes, 14)
        logger.info(f"✅ RSI(14): {rsi.iloc[-1]:.2f}")

        # Test VWAP
        vwap_val = vwap(df)
        logger.info(f"✅ VWAP: {vwap_val.iloc[-1]:.2f}")

        # Check for NaN values
        if fast_ma.isna().any():
            logger.warning("⚠️  Fast MA contains NaN values")
        if slow_ma.isna().any():
            logger.warning("⚠️  Slow MA contains NaN values")
        if rsi.isna().any():
            logger.warning("⚠️  RSI contains NaN values")
        if vwap_val.isna().any():
            logger.warning("⚠️  VWAP contains NaN values")

    except Exception as e:
        logger.error(f"❌ Indicator calculation failed: {e}", exc_info=True)


def analyze_market_conditions(df: pd.DataFrame):
    """Analyze market conditions to understand why signals might not trigger."""
    logger.info("=" * 60)
    logger.info("Market Conditions Analysis")
    logger.info("=" * 60)

    if df is None or df.empty:
        return

    try:
        from src.ta_indicators.ta_core import sma, rsi_ema, vwap

        closes = df["close"].astype(float)
        fast_ma = sma(closes, 10)
        slow_ma = sma(closes, 30)
        rsi = rsi_ema(closes, 14)
        vwap_val = vwap(df)

        # Analyze last 50 candles
        window = min(50, len(df))
        recent_df = df.iloc[-window:]

        # Count MA crossovers
        crossovers = 0
        for i in range(1, len(recent_df)):
            if fast_ma.iloc[-window+i-1] < slow_ma.iloc[-window+i-1] and \
               fast_ma.iloc[-window+i] > slow_ma.iloc[-window+i]:
                crossovers += 1

        logger.info(f"MA Crossovers (last {window} candles): {crossovers}")

        # Check price vs VWAP
        above_vwap = (closes.iloc[-window:] > vwap_val.iloc[-window:]).sum()
        logger.info(f"Candles above VWAP: {above_vwap}/{window} ({above_vwap/window*100:.1f}%)")

        # Check RSI range
        rsi_in_range = ((rsi.iloc[-window:] > 30) & (rsi.iloc[-window:] < 65)).sum()
        logger.info(f"RSI in range (30-65): {rsi_in_range}/{window} ({rsi_in_range/window*100:.1f}%)")

        # Current values
        logger.info(f"\nCurrent values:")
        logger.info(f"  Price: ${closes.iloc[-1]:.2f}")
        logger.info(f"  Fast MA: ${fast_ma.iloc[-1]:.2f}")
        logger.info(f"  Slow MA: ${slow_ma.iloc[-1]:.2f}")
        logger.info(f"  VWAP: ${vwap_val.iloc[-1]:.2f}")
        logger.info(f"  RSI: {rsi.iloc[-1]:.2f}")

        # Check each condition
        logger.info(f"\nSignal conditions:")
        logger.info(f"  ✓ Fast > Slow: {fast_ma.iloc[-1] > slow_ma.iloc[-1]}")
        logger.info(f"  ✓ Price > VWAP: {closes.iloc[-1] > vwap_val.iloc[-1]}")
        logger.info(f"  ✓ RSI in range: {30 < rsi.iloc[-1] < 65}")

    except Exception as e:
        logger.error(f"❌ Market analysis failed: {e}", exc_info=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Diagnose backtest issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="Trading symbol (default: BTCUSDT)",
    )

    parser.add_argument(
        "--interval",
        type=str,
        default="5",
        help="Candle interval in minutes (default: 5)",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to analyze (default: 30)",
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/zoomex_example.yaml",
        help="Configuration file path",
    )

    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use testnet for data fetching",
    )

    return parser.parse_args()


async def main():
    args = parse_args()

    logger.info("🔍 Backtest Diagnostic Tool")
    logger.info(f"Symbol: {args.symbol}")
    logger.info(f"Interval: {args.interval}m")
    logger.info(f"Days: {args.days}")
    logger.info("")

    # Test 1: Configuration
    config = test_configuration(args.config)

    # Test 2: Data Fetch
    df = await test_data_fetch(args.symbol, args.interval, args.days, args.testnet)

    if df is not None:
        # Test 3: Indicators
        test_indicators(df)

        # Test 4: Signal Generation
        test_signal_generation(df)

        # Test 5: Market Analysis
        analyze_market_conditions(df)

    logger.info("=" * 60)
    logger.info("Diagnostic Complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

async def test_data_fetch(symbol: str, interval: str, days: int, use_testnet: bool):
    """Test fetching historical data."""
    logger.info("=" * 60)
    logger.info("Testing Data Fetch")
    logger.info("=" * 60)

    base_url = (
        "https://openapi-testnet.zoomex.com"
        if use_testnet
        else "https://openapi.zoomex.com"
    )

    try:
        async with aiohttp.ClientSession() as session:
            # Use require_auth=False for public data endpoints
            client = ZoomexV3Client(
                session, 
                base_url=base_url, 
                category="linear",
                require_auth=False
            )

            logger.info(f"Fetching {symbol} {interval}m data...")
            df = await client.get_klines(symbol=symbol, interval=interval, limit=200)

            if df.empty:
                logger.error("❌ No data returned from API")
                return None

            logger.info(f"✅ Fetched {len(df)} candles")
            logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
            logger.info(f"   Columns: {list(df.columns)}")
            logger.info(f"   Latest close: ${df['close'].iloc[-1]:.2f}")

            return df

    except Exception as e:
        logger.error(f"❌ Data fetch failed: {e}", exc_info=True)
        return None

    try:
        async with aiohttp.ClientSession() as session:
            # Use require_auth=False for public data endpoints
            client = ZoomexV3Client(
                session, 
                base_url=base_url, 
                category="linear",
                require_auth=False
            )

            logger.info(f"Fetching {symbol} {interval}m data...")
            df = await client.get_klines(symbol=symbol, interval=interval, limit=200)

            if df.empty:
                logger.error("❌ No data returned from API")
                return None

            logger.info(f"✅ Fetched {len(df)} candles")
            logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
            logger.info(f"   Columns: {list(df.columns)}")
            logger.info(f"   Latest close: ${df['close'].iloc[-1]:.2f}")

            return df

    except Exception as e:
        logger.error(f"❌ Data fetch failed: {e}", exc_info=True)
        return None


    try:
        async with aiohttp.ClientSession() as session:
            # Use require_auth=False for public data endpoints
            client = ZoomexV3Client(
                session, 
                base_url=base_url, 
                category="linear",
                require_auth=False
            )

            logger.info(f"Fetching {symbol} {interval}m data...")
            df = await client.get_klines(symbol=symbol, interval=interval, limit=200)

            if df.empty:
                logger.error("❌ No data returned from API")
                return None

            logger.info(f"✅ Fetched {len(df)} candles")
            logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
            logger.info(f"   Columns: {list(df.columns)}")
            logger.info(f"   Latest close: ${df['close'].iloc[-1]:.2f}")

            return df

    except Exception as e:
        logger.error(f"❌ Data fetch failed: {e}", exc_info=True)
        return None

    try:
        async with aiohttp.ClientSession() as session:
            client = ZoomexV3Client(session, base_url=base_url, category="linear", require_auth=False)

            logger.info(f"Fetching {symbol} {interval}m data...")
            df = await client.get_klines(symbol=symbol, interval=interval, limit=200)

            if df.empty:
                logger.error("❌ No data returned from API")
                return None

            logger.info(f"✅ Fetched {len(df)} candles")
            logger.info(f"   Date range: {df.index[0]} to {df.index[-1]}")
            logger.info(f"   Columns: {list(df.columns)}")
            logger.info(f"   Latest close: ${df['close'].iloc[-1]:.2f}")

            return df

    except Exception as e:
        logger.error(f"❌ Data fetch failed: {e}", exc_info=True)
        return None
