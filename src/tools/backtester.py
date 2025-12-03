import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import aiohttp

from src.config import load_config, PerpsConfig, ExchangeConfig
from src.services.perps import PerpsService
from src.exchanges.replay_client import ReplayZoomexClient
from src.exchanges.ccxt_client import CCXTClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Backtester")

async def fetch_historical_data(
    symbol: str, interval: str, start_date: datetime, end_date: datetime, limit: int = 1000
) -> pd.DataFrame:
    """Fetch full historical data using CCXT."""
    
    # Create a temporary CCXT client
    # We can use a default config or load from file, but for data fetching we just need the provider
    config = ExchangeConfig(provider="bybit", name="bybit", testnet=False) # Default to bybit for data
    
    # We need to handle the loop here because CCXTClient.get_historical_data might limit results
    # But CCXTClient.get_historical_data implementation in this codebase seems to fetch a single chunk?
    # Let's check CCXTClient.get_historical_data implementation.
    # It calls fetch_ohlcv. ccxt fetch_ohlcv usually returns up to 1000 candles.
    # So we need a loop here similar to the original one.
    
    client = CCXTClient(config)
    await client.initialize()
    
    try:
        all_klines = []
        current_start = start_date
        
        logger.info(f"Fetching data for {symbol} from {start_date} to {end_date} using CCXT...")
        
        while current_start < end_date:
            # Calculate limit based on interval to optimize?
            # CCXT usually handles limit.
            
            # We need to fetch from current_start
            # CCXT fetch_ohlcv takes 'since' in ms.
            since_ts = int(current_start.timestamp() * 1000)
            
            try:
                # We use the public method if available, or just use the internal ccxt instance
                # CCXTClient has get_historical_data but it takes 'limit'.
                # It doesn't seem to take 'start_time'.
                # I should check CCXTClient again.
                # If it doesn't support start_time, I might need to extend it or access .ccxt directly.
                
                # Let's assume I can access client.ccxt if needed, or better, use get_historical_data if it supports it.
                # The previous view of CCXTClient showed get_historical_data(symbol, timeframe, limit).
                # It didn't show 'since'.
                # I should probably use client.ccxt.fetch_ohlcv directly for this specific backfill task
                # OR update CCXTClient to support 'since'.
                # Updating CCXTClient is cleaner.
                
                # For now, I will use client.ccxt directly to avoid modifying CCXTClient again if possible,
                # but CCXTClient wrapper is preferred.
                # Let's check if I can pass 'since' to get_historical_data.
                # The signature was get_historical_data(self, symbol: str, timeframe: str, limit: int = 200) -> Optional[pd.DataFrame]
                
                # So I should use client.ccxt.fetch_ohlcv
                if client.ccxt is None:
                     await client.initialize()
                     
                ohlcv = await client.ccxt.fetch_ohlcv(symbol, interval, since=since_ts, limit=limit)
                
                if not ohlcv:
                    break
                    
                # Convert to DataFrame
                # CCXT returns [timestamp, open, high, low, close, volume]
                chunk = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                chunk["timestamp"] = pd.to_datetime(chunk["timestamp"], unit="ms", utc=True)
                chunk.set_index("timestamp", inplace=True)
                
                all_klines.append(chunk)
                
                last_time = chunk.index[-1]
                if last_time <= current_start:
                     # No progress
                     break
                
                current_start = last_time + timedelta(milliseconds=1) # Move forward
                
                logger.info(f"Fetched chunk ending at {last_time}")
                
                await asyncio.sleep(client.ccxt.rateLimit / 1000.0 if client.ccxt.rateLimit else 0.1)

            except Exception as e:
                logger.error(f"Error fetching data: {e}")
                break
        
        if not all_klines:
            return pd.DataFrame()

        full_df = pd.concat(all_klines)
        full_df = full_df[~full_df.index.duplicated(keep='first')]
        final_df = full_df[(full_df.index >= start_date) & (full_df.index <= end_date)]
        
        logger.info(f"Fetched {len(final_df)} rows.")
        return final_df
        
    finally:
        await client.close()

async def run_backtest(args):
    start_dt = datetime.fromisoformat(args.start_date.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(args.end_date.replace("Z", "+00:00"))
    
    df = await fetch_historical_data(args.symbol, args.interval, start_dt, end_dt)
    if df.empty:
        logger.error("No data fetched.")
        return

    # Load base config but override perps
    config = load_config()
    config.perps.symbol = args.symbol
    config.perps.interval = args.interval
    config.perps.mode = "backtest"
    config.perps.enabled = True
    
    # Setup services
    async with aiohttp.ClientSession() as session:
        perps_service = PerpsService(config.perps, session)
        
        # Inject Replay Client
        replay_client = ReplayZoomexClient(df, session, initial_capital=args.initial_capital)
        perps_service.client = replay_client
        
        await perps_service.initialize()
        # Initialize mocks account state
        await perps_service._refresh_account_state()
        perps_service.equity_usdt = args.initial_capital
        
        logger.info("Starting backtest simulation...")
        
        # Simulation Loop
        # Iterate through the DataFrame time index
        # For each step:
        # 1. Update replay_client time
        # 2. Run perps_service.run_cycle()
        
        # Determine step size based on interval
        # But we can just iterate through unique timestamps in df
        timestamps = df.index.unique().sort_values()
        
        # Determine warmup period (e.g. first 100 candles)
        warmup = 100
        if len(timestamps) < warmup:
            logger.error("Not enough data for warmup.")
            return
            
        for i, current_time in enumerate(timestamps):
            if i < warmup:
                continue
                
            replay_client.set_time(current_time)
            
            # Override perps_service time checking (it usually uses datetime.now())
            # This is tricky because perps_service might check now() for other things.
            # Ideally we should patch datetime, but let's see if get_klines is enough.
            # PerpsService uses client.get_klines which is mocked.
            
            await perps_service.run_cycle()
                 
            # Log progress
            if i % 100 == 0:
                pct = (i / len(timestamps)) * 100
                equity = await replay_client.get_wallet_equity()
                logger.info(f"Progress: {pct:.1f}% - Time: {current_time} - Equity: ${equity:.2f}")
        
        final_equity = await replay_client.get_wallet_equity()
        logger.info("=" * 60)
        logger.info(f"Backtest Complete.")
        logger.info(f"Initial Capital: ${args.initial_capital}")
        logger.info(f"Final Equity:    ${final_equity:.2f}")
        logger.info(f"PnL:             ${final_equity - args.initial_capital:.2f}")
        logger.info("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtester Tool")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--interval", type=str, default="15")
    parser.add_argument("--start-date", type=str, required=True, help="ISO format e.g. 2023-01-01T00:00:00")
    parser.add_argument("--end-date", type=str, required=True, help="ISO format")
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    
    args = parser.parse_args()
    asyncio.run(run_backtest(args))
