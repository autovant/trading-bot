import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from .shadow_client import ShadowZoomexClient

logger = logging.getLogger(__name__)

class ReplayZoomexClient(ShadowZoomexClient):
    """
    Zoomex client for Backtesting/Replay.
    
    It serves historical data as if it were live.
    Requires a pre-loaded DataFrame of candles.
    """

    def __init__(self, df: pd.DataFrame, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.df = df.sort_index() # Index should be localized datetime
        self._current_time: Optional[datetime] = None
        
        # Validate dataframe
        required_cols = ["open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in self.df.columns:
                raise ValueError(f"DataFrame missing required column: {col}")

    def set_time(self, dt: datetime):
        """Advance the simulated time."""
        self._current_time = dt

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 200, **kwargs
    ) -> pd.DataFrame:
        if self._current_time is None:
             raise RuntimeError("Replay time not set. Call set_time() first.")

        # Get slice ending at current_time (inclusive/exclusive dependence on matching logic)
        # Assuming current_time is "now", so we want candles closed before now, 
        # or including the possibly open candle?
        # PerpsService expects closed candles mostly.
        
        # Slice: index <= current_time
        # Take last 'limit' rows
        
        slice_df = self.df[self.df.index <= self._current_time]
        if slice_df.empty:
            return pd.DataFrame()
        
        return slice_df.iloc[-limit:].copy()

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        # Return last close price as current price
        if self._current_time is None:
             return {"lastPrice": "0.0"}
        
        slice_df = self.df[self.df.index <= self._current_time]
        if slice_df.empty:
            return {"lastPrice": "0.0"}
            
        price = slice_df.iloc[-1]["close"]
        return {"lastPrice": str(price)}
        
    async def get_tickers(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        # Wrapper for get_ticker returning list
        ticker = await self.get_ticker(symbol or "")
        return {"list": [ticker]}
