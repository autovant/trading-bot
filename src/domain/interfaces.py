from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from datetime import datetime
import pandas as pd
import polars as pl
from .entities import Order, Trade, Position, Signal, MarketData

class IDataFeed(ABC):
    @abstractmethod
    async def subscribe(self, symbols: List[str]): ...
    
    @abstractmethod
    async def get_historical_data(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame: ...

class IExecutionEngine(ABC):
    @abstractmethod
    async def submit_order(self, order: Order) -> Order: ...
    
    @abstractmethod
    async def cancel_order(self, order_id: str): ...
    
    @abstractmethod
    async def get_positions(self) -> List[Position]: ...

class IStrategy(ABC):
    @abstractmethod
    async def on_tick(self, market_data: MarketData) -> Optional[List[Order]]: ...
    
    @abstractmethod
    async def on_bar(self, market_data: MarketData, timeframe: str) -> Optional[List[Order]]: ...
    
    @abstractmethod
    async def on_order_update(self, order: Order): ...

    def vectorized_signals(self, data: pl.DataFrame) -> Optional[pl.DataFrame]:
        """
        Optional fast-path: return a Polars DataFrame with a 'signal' column
        representing position (+1 long, -1 short, 0 flat) aligned to input rows.
        """
        return None

class IRepository(ABC):
    @abstractmethod
    async def save_trade(self, trade: Trade): ...
    
    @abstractmethod
    async def get_trades(self, symbol: str) -> List[Trade]: ...
