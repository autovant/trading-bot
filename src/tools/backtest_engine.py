import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import pandas as pd
import plotly.graph_objects as go

from src.config import load_config, PerpsConfig
from src.services.perps import PerpsService
from src.exchanges.replay_client import ReplayZoomexClient
from src.exchanges.zoomex_v3 import ZoomexV3Client

logger = logging.getLogger("BacktestEngine")

class BacktestEngine:
    def __init__(self):
        self.logs = []

    async def fetch_historical_data(
        self, symbol: str, interval: str, start_date: datetime, end_date: datetime, limit: int = 1000
    ) -> pd.DataFrame:
        """Fetch full historical data from Zoomex."""
        # Reuse logic from CLI tool, but localized here
        interval_map = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60, "240": 240, "D": 1440}
        interval_minutes = interval_map.get(interval, 1)
        
        async with aiohttp.ClientSession() as session:
            client = ZoomexV3Client(session, base_url="https://openapi.zoomex.com")
            
            all_klines = []
            current_end = end_date
            
            while current_end > start_date:
                end_ts = int(current_end.timestamp() * 1000)
                try:
                    chunk = await client.get_klines(symbol=symbol, interval=interval, limit=limit, end=end_ts)
                except Exception as e:
                    logger.error(f"Error fetching data: {e}")
                    break
                    
                if chunk.empty:
                    break
                
                all_klines.append(chunk)
                oldest_time = chunk.index[0]
                
                if oldest_time >= current_end:
                    current_end -= timedelta(minutes=interval_minutes * limit)
                else:
                    current_end = oldest_time
                
                # Rate limit protection
                await asyncio.sleep(0.1)
                
        if not all_klines:
            return pd.DataFrame()

        full_df = pd.concat(all_klines)
        full_df = full_df.sort_index()
        full_df = full_df[~full_df.index.duplicated(keep='first')]
        return full_df[(full_df.index >= start_date) & (full_df.index <= end_date)]

    async def run(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        risk_pct: float = 0.02,
        leverage: int = 5,
        use_multi_tf: bool = False
    ) -> Dict[str, Any]:

        df = await self.fetch_historical_data(symbol, interval, start_date, end_date)
        if df.empty:
            return {"error": "No data fetched"}

        config = load_config()
        config.perps.useMultiTfAtrStrategy = use_multi_tf
        config.perps.symbol = symbol
        config.perps.interval = interval
        config.perps.mode = "backtest"
        config.perps.enabled = True
        config.perps.riskPct = risk_pct
        config.perps.leverage = leverage
        
        # Capture equity curve
        equity_curve = []
        
        async with aiohttp.ClientSession() as session:
            perps_service = PerpsService(config.perps, session)
            replay_client = ReplayZoomexClient(df, session, initial_capital=initial_capital)
            perps_service.client = replay_client
            
            await perps_service.initialize()
            await perps_service._refresh_account_state()
            perps_service.equity_usdt = initial_capital
            
            timestamps = df.index.unique().sort_values()
            warmup = 100
            
            for i, current_time in enumerate(timestamps):
                if i < warmup:
                    continue
                    
                replay_client.set_time(current_time)
                await perps_service.run_cycle()
                
                # Snapshot
                if i % 4 == 0: # Store every 4th candle to save memory/time if needed
                    eq = await replay_client.get_wallet_equity()
                    equity_curve.append({"time": current_time, "equity": eq})
            
            final_equity = await replay_client.get_wallet_equity()
            
            # Construct result
            df_equity = pd.DataFrame(equity_curve)
            if not df_equity.empty:
                df_equity.set_index("time", inplace=True)
                
            # Calculate basic stats
            total_return = (final_equity - initial_capital) / initial_capital

            return {
                "equity_curve": df_equity,
                "final_equity": final_equity,
                "total_return": total_return,
                "initial_capital": initial_capital,
                "symbol": symbol,
                "interval": interval,
                "strategy": "Multi-TF" if use_multi_tf else "Simple"
            }
