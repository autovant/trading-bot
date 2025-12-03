#!/usr/bin/env python3
"""
Real-time monitoring dashboard for the trading bot.

Displays:
- Current position
- Account balance
- Recent trades
- Performance metrics
- Live signals

Usage:
    python tools/monitor.py --config configs/zoomex_example.yaml
    python tools/monitor.py --config configs/zoomex_example.yaml --mode testnet
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.exchanges.zoomex_v3 import ZoomexV3Client
from src.strategies.perps_trend_vwap import compute_signals

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class TradingMonitor:
    def __init__(self, config_path: str, mode: str):
        self.config_path = config_path
        self.mode = mode
        self.client = None
        self.session = None

    async def initialize(self):
        os.environ["CONFIG_PATH"] = self.config_path
        self.config = get_config()

        base_url = (
            "https://openapi-testnet.zoomex.com"
            if self.mode == "testnet"
            else "https://openapi.zoomex.com"
        )

        self.session = aiohttp.ClientSession()
        self.client = ZoomexV3Client(self.session, base_url=base_url, mode_name=self.mode)

    async def get_account_info(self):
        equity = await self.client.get_wallet_equity()
        position_qty = await self.client.get_position_qty(
            self.config.perps.symbol,
            self.config.perps.positionIdx
        )
        return equity, position_qty

    async def get_current_signals(self):
        df = await self.client.get_klines(
            symbol=self.config.perps.symbol,
            interval=self.config.perps.interval,
            limit=100
        )

        if df.empty or len(df) < 35:
            return None

        signals = compute_signals(df)
        return signals

    async def display_dashboard(self):
        while True:
            try:
                os.system('cls' if os.name == 'nt' else 'clear')

                print("=" * 80)
                print(f"{'Zoomex Trading Bot - Live Monitor':^80}")
                print("=" * 80)
                print(f"Mode: {self.mode.upper():^80}")
                print(f"Symbol: {self.config.perps.symbol:^80}")
                print(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^80}")
                print("=" * 80)

                equity, position_qty = await self.get_account_info()

                print("\n📊 Account Status")
                print("-" * 80)
                print(f"  Equity: ${equity:.2f}")
                print(f"  Position: {position_qty:.6f} {self.config.perps.symbol}")
                print(f"  Leverage: {self.config.perps.leverage}x")

                signals = await self.get_current_signals()

                if signals:
                    print("\n📈 Current Signals")
                    print("-" * 80)
                    print(f"  Price: {signals['price']:.4f}")
                    print(f"  Fast MA: {signals['fast']:.4f}")
                    print(f"  Slow MA: {signals['slow']:.4f}")
                    print(f"  VWAP: {signals['vwap']:.4f}")
                    print(f"  RSI: {signals['rsi']:.2f}")
                    print(f"  Volume: {signals['volume']:.2f}")

                    if signals['long_signal']:
                        print("\n  🟢 LONG SIGNAL ACTIVE")
                    else:
                        print("\n  ⚪ No signal")

                if position_qty > 0:
                    print("\n💼 Active Position")
                    print("-" * 80)
                    print(f"  Quantity: {position_qty:.6f}")
                    print(f"  Side: LONG")

                    if signals:
                        current_price = signals['price']
                        tp_price = current_price * (1 + self.config.perps.takeProfitPct)
                        sl_price = current_price * (1 - self.config.perps.stopLossPct)

                        print(f"  Current Price: {current_price:.4f}")
                        print(f"  Take Profit: {tp_price:.4f}")
                        print(f"  Stop Loss: {sl_price:.4f}")

                print("\n" + "=" * 80)
                print("Press Ctrl+C to exit")
                print("=" * 80)

                await asyncio.sleep(10)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")
                await asyncio.sleep(5)

    async def shutdown(self):
        if self.session:
            await self.session.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Real-time trading bot monitor",
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
        help="API mode (default: testnet)",
    )

    return parser.parse_args()


async def main():
    args = parse_args()

    monitor = TradingMonitor(args.config, args.mode)

    try:
        await monitor.initialize()
        await monitor.display_dashboard()
    except KeyboardInterrupt:
        print("\n\nShutting down monitor...")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
    finally:
        await monitor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
