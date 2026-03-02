"""
Scenario Finder
Scans recent historical data to find a clear Long/Short trade sequence
that we can replay for the user.
"""

import asyncio
import logging
import pandas as pd
from datetime import datetime, timezone
import httpx
from typing import List, Dict, Optional

from src.signal_generator import SignalGenerator
from src.config import get_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    # Use bybit public API for easy gathering
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": "60" if interval == "1h" else ("240" if interval == "4h" else "D"),
        "limit": limit
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        data = resp.json()
        if data["retCode"] != 0:
            raise Exception(f"Bybit API Error: {data}")
            
        # Parse
        raw = data["result"]["list"] # [start, open, high, low, close, volume, turnover]
        # Bybit returns reversed list (newest first)
        raw.reverse()
        
        df = pd.DataFrame(raw, columns=["start", "open", "high", "low", "close", "volume", "turnover"])
        df["start"] = pd.to_numeric(df["start"])
        df["open"] = pd.to_numeric(df["open"])
        df["high"] = pd.to_numeric(df["high"])
        df["low"] = pd.to_numeric(df["low"])
        df["close"] = pd.to_numeric(df["close"])
        df["volume"] = pd.to_numeric(df["volume"])
        
        # Convert ms to datetime
        df.index = pd.to_datetime(df["start"], unit="ms", utc=True)
        return df

async def find_scenario():
    logger.info("Fetching Data...")
    
    # Needs enough data for indicators
    df_1d = await fetch_klines("SOLUSDT", "1d", 200)
    df_4h = await fetch_klines("SOLUSDT", "4h", 300)
    df_1h = await fetch_klines("SOLUSDT", "1h", 1000)
    
    logger.info(f"Data fetched: 1D={len(df_1d)}, 4H={len(df_4h)}, 1H={len(df_1h)}")
    
    gen = SignalGenerator()
    config = get_config().strategy
    
    # We simulate a sliding window over the 1H data
    # We need 1d and 4k data that aligns... 
    # For simplicity, we'll just take the latest 1d/4h as context 
    # (assuming regime doesn't flip constantly) and scan 1H for entry/exit
    
    regime = gen.detect_regime(df_1d, config)
    setup = gen.detect_setup(df_4h, config)
    
    logger.info(f"Global Context -> Regime: {regime.regime}, Setup: {setup.direction}")
    
    # Look for a sequence
    # 1. No Position
    # 2. Entry Signal
    # 3. Hold
    # 4. Exit Signal (Strategy exit, not just TP/SL)
    
    in_trade = False
    entry_price = 0.0
    entry_idx = 0
    
    best_scenario = None
    
    # Warmup
    warmup = 50
    for i in range(warmup, len(df_1h)):
        # Window
        current_df = df_1h.iloc[i-warmup:i+1]
        
        signals = gen.generate_signals(current_df, config)
        valid = gen.filter_signals(signals, regime, setup)
        
        # Determine exit logic manually since 'SignalGenerator' mainly does entries
        # But we need to know when to exit.
        # Strategy exit logic is usually in PerpsService._manage_open_position_strategy
        # Replicating simple trend flip or confirmation logic here
        
        # Simple Exit condition: Trend Reversal in 1H
        # or just Price hitting targets.
        
        if not in_trade:
            # Look for entry
            if valid:
                sig = valid[0] # Take first
                in_trade = True
                entry_price = sig.entry_price
                entry_idx = i
                # logger.info(f"Found Entry Candidate at {current_df.index[-1]} - {sig.direction}")
        else:
            # Look for exit
            curr_price = current_df.iloc[-1]["close"]
            # Mock exit check: Close crossing SMA20 significantly?
            # Or just wait for 'reverse' signal?
            
            # Use raw signals to see if we get opposite signal
            if valid and valid[0].direction != setup.direction:
                 # Opposite signal?
                 pass
                 
            # If we held for > 5 hours and made profit > 1%
            duration = i - entry_idx
            pnl_pct = (curr_price - entry_price) / entry_price
            
            if duration > 5 and abs(pnl_pct) > 0.02:
                in_trade = False
                logger.info(f"SCENARIO FOUND: Entry idx {entry_idx} -> Exit idx {i} (PnL: {pnl_pct*100:.2f}%)")
                
                return {
                    "start_idx": entry_idx - 5, # Start a bit before
                    "end_idx": i + 2,
                    "df_1h": df_1h,
                    "df_4h": df_4h,
                    "df_1d": df_1d
                }

    logger.warning("No perfect scenarios found in recent window. Using fallback.")
    return None

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(find_scenario())
