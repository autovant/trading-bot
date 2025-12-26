import argparse
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from src.config import ExchangeConfig, load_config
from src.database import DatabaseManager
from src.exchange import ExchangeClient
from src.strategy import TradingStrategy
from src.tools.backtester import fetch_historical_data

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BacktestStrategy")


class MockExchangeClient(ExchangeClient):
    def __init__(self, config: ExchangeConfig, df: pd.DataFrame):
        # Initialize with dummy config and mode
        super().__init__(config, app_mode="replay")
        self.full_df = df
        self.current_time = df.index[0]
        self._order_book_cache: Dict[str, Any] = {}

    def set_time(self, dt: datetime):
        self.current_time = dt

    async def get_historical_data(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[pd.DataFrame]:
        # Return slice of df up to current_time
        # Assuming df is 1m or matching timeframe.
        # For simplicity, we assume the input DF matches the requested timeframe or we resample.
        # Here we just slice.

        mask = self.full_df.index <= self.current_time
        sliced = self.full_df.loc[mask]
        return sliced.iloc[-limit:]

    async def get_order_book(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        # Mock order book or return None
        # User said: "Where backtest data lacks full order book, degrade gracefully: no crashes, just skip those signals."
        # We can return a dummy order book to test the *logic* if we want, or None.
        # Let's return None by default, or a dummy if requested.
        return None

    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        # Return last close
        mask = self.full_df.index <= self.current_time
        sliced = self.full_df.loc[mask]
        if sliced.empty:
            return {"lastPrice": 0.0}
        return {"lastPrice": sliced.iloc[-1]["close"]}

    async def place_order(self, **kwargs):
        # Mock order placement
        logger.info(f"MOCK ORDER: {kwargs}")
        return None


async def run_backtest(args):
    start_dt = datetime.fromisoformat(args.start_date.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(args.end_date.replace("Z", "+00:00"))

    logger.info("Fetching historical data...")
    df = await fetch_historical_data(args.symbol, args.interval, start_dt, end_dt)
    if df.empty:
        logger.error("No data fetched.")
        return

    config = load_config()
    # Enable VWAP for testing
    config.strategy.vwap.enabled = True
    config.strategy.vwap.mode = "session"

    # Mock Database
    db = DatabaseManager(":memory:")
    await db.initialize()

    # Mock Exchange
    exchange = MockExchangeClient(config.exchange, df)

    strategy = TradingStrategy(
        config=config, exchange=exchange, database=db, run_id="backtest_run"
    )

    logger.info("Starting backtest...")

    timestamps = df.index.unique().sort_values()

    for i, current_time in enumerate(timestamps):
        exchange.set_time(current_time)

        # We need to manually trigger what the loop does
        # update_market_data calls get_historical_data
        await strategy.update_market_data()
        await strategy.run_analysis()

        if i % 100 == 0:
            logger.info(f"Processed {i}/{len(timestamps)} candles")

    logger.info("Backtest complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategy Backtester")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--interval", type=str, default="1h")
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)

    args = parser.parse_args()
    asyncio.run(run_backtest(args))
