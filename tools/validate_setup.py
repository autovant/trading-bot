#!/usr/bin/env python3
"""
Configuration and API validation script.

Validates:
- Environment variables
- Configuration file
- API connectivity
- Account permissions
- Symbol availability

Usage:
    python tools/validate_setup.py --config configs/zoomex_example.yaml
    python tools/validate_setup.py --config configs/zoomex_example.yaml --mode testnet
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import aiohttp
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.exchanges.zoomex_v3 import ZoomexV3Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class ValidationResult:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []

    def add_pass(self, message: str):
        self.passed.append(message)
        logger.info(f"✅ {message}")

    def add_fail(self, message: str):
        self.failed.append(message)
        logger.error(f"❌ {message}")

    def add_warning(self, message: str):
        self.warnings.append(message)
        logger.warning(f"⚠️  {message}")

    def print_summary(self):
        logger.info("=" * 60)
        logger.info("Validation Summary")
        logger.info("=" * 60)
        logger.info(f"Passed: {len(self.passed)}")
        logger.info(f"Failed: {len(self.failed)}")
        logger.info(f"Warnings: {len(self.warnings)}")
        logger.info("=" * 60)

        if self.failed:
            logger.error("Failed checks:")
            for msg in self.failed:
                logger.error(f"  - {msg}")
            return False
        else:
            logger.info("✅ All validation checks passed!")
            if self.warnings:
                logger.warning("Warnings:")
                for msg in self.warnings:
                    logger.warning(f"  - {msg}")
            return True


async def validate_environment(result: ValidationResult):
    logger.info("Validating environment variables...")

    required_vars = ["ZOOMEX_API_KEY", "ZOOMEX_API_SECRET"]
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            result.add_fail(f"Missing environment variable: {var}")
        elif len(value) < 10:
            result.add_fail(f"Invalid {var}: too short")
        else:
            result.add_pass(f"{var} is set ({value[:8]}...)")


async def validate_config_file(config_path: str, result: ValidationResult):
    logger.info(f"Validating configuration file: {config_path}")

    if not Path(config_path).exists():
        result.add_fail(f"Configuration file not found: {config_path}")
        return None

    result.add_pass(f"Configuration file exists: {config_path}")

    try:
        with open(config_path, "r") as f:
            config_data = yaml.safe_load(f)
        result.add_pass("Configuration file is valid YAML")
    except Exception as e:
        result.add_fail(f"Failed to parse configuration: {e}")
        return None

    if "perps" not in config_data:
        result.add_fail("Missing 'perps' section in configuration")
        return None

    perps_config = config_data["perps"]

    required_fields = ["symbol", "interval", "leverage", "riskPct", "stopLossPct", "takeProfitPct"]
    for field in required_fields:
        if field not in perps_config:
            result.add_fail(f"Missing required field in perps config: {field}")
        else:
            result.add_pass(f"Field '{field}' is set: {perps_config[field]}")

    if perps_config.get("leverage", 0) > 10:
        result.add_warning(f"High leverage detected: {perps_config['leverage']}x")

    if perps_config.get("riskPct", 0) > 0.02:
        result.add_warning(f"High risk per trade: {perps_config['riskPct'] * 100:.2f}%")

    return config_data


async def validate_api_connectivity(mode: str, result: ValidationResult):
    logger.info(f"Validating API connectivity ({mode})...")

    api_key = os.getenv("ZOOMEX_API_KEY")
    api_secret = os.getenv("ZOOMEX_API_SECRET")

    if not api_key or not api_secret:
        result.add_fail("Cannot test API: credentials not set")
        return

    base_url = (
        "https://openapi-testnet.zoomex.com"
        if mode == "testnet"
        else "https://openapi.zoomex.com"
    )

    async with aiohttp.ClientSession() as session:
        client = ZoomexV3Client(session, base_url=base_url, mode_name=mode)

        try:
            equity = await client.get_wallet_equity()
            result.add_pass(f"API connection successful (equity: ${equity:.2f})")
        except Exception as e:
            result.add_fail(f"API connection failed: {e}")
            return

        try:
            positions = await client.get_position_qty("BTCUSDT", 0)
            result.add_pass(f"Position query successful (BTCUSDT qty: {positions})")
        except Exception as e:
            result.add_fail(f"Position query failed: {e}")


async def validate_symbol(symbol: str, mode: str, result: ValidationResult):
    logger.info(f"Validating symbol: {symbol}")

    base_url = (
        "https://openapi-testnet.zoomex.com"
        if mode == "testnet"
        else "https://openapi.zoomex.com"
    )

    async with aiohttp.ClientSession() as session:
        client = ZoomexV3Client(session, base_url=base_url, mode_name=mode)

        try:
            info = await client.get_instruments_info(symbol)
            result.add_pass(f"Symbol {symbol} is available")
            result.add_pass(f"  Min quantity: {info.min_qty}")
            result.add_pass(f"  Quantity step: {info.qty_step}")
            result.add_pass(f"  Price tick: {info.price_tick}")
        except Exception as e:
            result.add_fail(f"Symbol validation failed: {e}")


async def validate_historical_data(symbol: str, interval: str, mode: str, result: ValidationResult):
    logger.info(f"Validating historical data: {symbol} {interval}m")

    base_url = (
        "https://openapi-testnet.zoomex.com"
        if mode == "testnet"
        else "https://openapi.zoomex.com"
    )

    async with aiohttp.ClientSession() as session:
        client = ZoomexV3Client(session, base_url=base_url, mode_name=mode)

        try:
            df = await client.get_klines(symbol=symbol, interval=interval, limit=100)
            if df.empty:
                result.add_fail(f"No historical data available for {symbol}")
            elif len(df) < 35:
                result.add_warning(f"Limited historical data: {len(df)} candles (need 35+ for indicators)")
            else:
                result.add_pass(f"Historical data available: {len(df)} candles")
                result.add_pass(f"  Latest candle: {df.index[-1]}")
        except Exception as e:
            result.add_fail(f"Historical data query failed: {e}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate trading bot setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--config",
        type=str,
        default="configs/zoomex_example.yaml",
        help="Configuration file path",
    )

    parser.add_argument(
        "--mode",
        type=str,
        default="testnet",
        choices=["testnet", "live"],
        help="API mode to validate (default: testnet)",
    )

    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Skip API connectivity tests",
    )

    return parser.parse_args()


async def main():
    args = parse_args()

    result = ValidationResult()

    logger.info("=" * 60)
    logger.info("Trading Bot Setup Validation")
    logger.info("=" * 60)

    await validate_environment(result)

    config_data = await validate_config_file(args.config, result)

    if not args.skip_api and config_data:
        await validate_api_connectivity(args.mode, result)

        if "perps" in config_data:
            symbol = config_data["perps"].get("symbol", "BTCUSDT")
            interval = str(config_data["perps"].get("interval", "5"))

            await validate_symbol(symbol, args.mode, result)
            await validate_historical_data(symbol, interval, args.mode, result)

    result.print_summary()

    if not result.failed:
        logger.info("=" * 60)
        logger.info("✅ Setup is ready for trading!")
        logger.info("=" * 60)
        sys.exit(0)
    else:
        logger.error("=" * 60)
        logger.error("❌ Setup validation failed")
        logger.error("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
