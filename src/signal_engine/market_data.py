"""
Market Data Service for the Confluence Signal Engine.

CCXT-based market data ingestion with:
- Incremental OHLCV fetching (only new candles)
- Candle-close detection
- In-memory + DB caching
- Data gap detection
- Rate limit handling with backoff
- Bounded asyncio concurrency
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import ccxt.async_support as ccxt
import pandas as pd

from src.signal_engine.config import timeframe_to_seconds
from src.signal_engine.schemas import CandleData, SubscriptionConfig

logger = logging.getLogger(__name__)


class MarketDataService:
    """
    CCXT-based market data ingestion service.
    
    Features:
    - Incremental fetching (only new candles since last timestamp)
    - Candle-close detection based on timeframe
    - In-memory caching with configurable size
    - Data gap detection
    - Rate limit handling with exponential backoff
    - Bounded concurrency per exchange
    """
    
    def __init__(
        self,
        max_cache_size: int = 500,
        max_concurrent_per_exchange: int = 5,
        retry_attempts: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize market data service.
        
        Args:
            max_cache_size: Max candles to cache per subscription
            max_concurrent_per_exchange: Max concurrent requests per exchange
            retry_attempts: Number of retry attempts on failure
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.max_cache_size = max_cache_size
        self.max_concurrent = max_concurrent_per_exchange
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        
        # Exchange instances (lazy initialized)
        self._exchanges: Dict[str, ccxt.Exchange] = {}
        
        # Semaphores for rate limiting per exchange
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        
        # In-memory candle cache: (exchange, symbol, tf) -> DataFrame
        self._cache: Dict[tuple, pd.DataFrame] = {}
        
        # Last fetched timestamp per subscription
        self._last_ts: Dict[tuple, datetime] = {}
        
        # Degraded stream tracking
        self._degraded: Set[tuple] = set()
    
    async def initialize_exchange(self, exchange_id: str, config: Optional[Dict] = None) -> None:
        """
        Initialize an exchange connection.
        
        Args:
            exchange_id: CCXT exchange ID (e.g., "bybit", "binance")
            config: Optional exchange config (api key, etc.)
        """
        if exchange_id in self._exchanges:
            return
        
        config = config or {}
        
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({
                "enableRateLimit": True,
                "timeout": 30000,
                **config,
            })
            
            await exchange.load_markets()
            self._exchanges[exchange_id] = exchange
            self._semaphores[exchange_id] = asyncio.Semaphore(self.max_concurrent)
            
            logger.info(f"Initialized exchange: {exchange_id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize exchange {exchange_id}: {e}")
            raise
    
    async def close_all(self) -> None:
        """Close all exchange connections."""
        for exchange_id, exchange in self._exchanges.items():
            try:
                await exchange.close()
                logger.info(f"Closed exchange: {exchange_id}")
            except Exception as e:
                logger.error(f"Error closing {exchange_id}: {e}")
        
        self._exchanges.clear()
        self._semaphores.clear()
    
    async def fetch_candles(
        self,
        exchange_id: str,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        since: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candles from exchange.
        
        Args:
            exchange_id: Exchange ID
            symbol: Trading symbol (e.g., "BTC/USDT")
            timeframe: CCXT timeframe (e.g., "1h")
            limit: Max candles to fetch
            since: Fetch candles since this time (incremental)
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if exchange_id not in self._exchanges:
            await self.initialize_exchange(exchange_id)
        
        exchange = self._exchanges[exchange_id]
        semaphore = self._semaphores[exchange_id]
        
        since_ms = int(since.timestamp() * 1000) if since else None
        
        for attempt in range(self.retry_attempts):
            try:
                async with semaphore:
                    ohlcv = await exchange.fetch_ohlcv(
                        symbol=symbol,
                        timeframe=timeframe,
                        since=since_ms,
                        limit=limit,
                    )
                
                if not ohlcv:
                    return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
                
                df = pd.DataFrame(
                    ohlcv,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                
                return df
                
            except ccxt.RateLimitExceeded as e:
                delay = self.retry_delay * (2 ** attempt)
                logger.warning(f"Rate limit hit for {exchange_id}, retrying in {delay}s")
                await asyncio.sleep(delay)
                
            except ccxt.NetworkError as e:
                delay = self.retry_delay * (2 ** attempt)
                logger.warning(f"Network error for {exchange_id}: {e}, retrying in {delay}s")
                await asyncio.sleep(delay)
                
            except Exception as e:
                logger.error(f"Failed to fetch candles for {symbol}: {e}")
                if attempt == self.retry_attempts - 1:
                    raise
                await asyncio.sleep(self.retry_delay)
        
        raise RuntimeError(f"Failed to fetch candles after {self.retry_attempts} attempts")
    
    async def update_subscription(
        self,
        subscription: SubscriptionConfig,
    ) -> tuple[pd.DataFrame, bool, bool]:
        """
        Update data for a subscription (incremental fetch).
        
        Args:
            subscription: Subscription to update
            
        Returns:
            Tuple of (DataFrame, candle_closed, data_degraded)
        """
        key = (subscription.exchange, subscription.symbol, subscription.timeframe)
        
        # Get timeframe duration
        tf_seconds = timeframe_to_seconds(subscription.timeframe)
        
        # Determine fetch start time
        since = self._last_ts.get(key)
        if since:
            # Fetch a bit earlier to catch any missed candles
            since = since - timedelta(seconds=tf_seconds * 2)
        
        # Convert symbol format if needed (e.g., BTCUSDT -> BTC/USDT)
        symbol = self._normalize_symbol(subscription.symbol)
        
        try:
            new_candles = await self.fetch_candles(
                exchange_id=subscription.exchange,
                symbol=symbol,
                timeframe=subscription.timeframe,
                limit=200 if since is None else 50,
                since=since,
            )
        except Exception as e:
            logger.error(f"Failed to update {key}: {e}")
            self._degraded.add(key)
            
            # Return cached data with degraded flag
            cached = self._cache.get(key, pd.DataFrame())
            return cached, False, True
        
        if new_candles.empty:
            cached = self._cache.get(key, pd.DataFrame())
            return cached, False, key in self._degraded
        
        # Update cache
        self._update_cache(key, new_candles)
        
        # Check for data gaps
        data_degraded = self._check_gaps(key, tf_seconds)
        if data_degraded:
            self._degraded.add(key)
        else:
            self._degraded.discard(key)
        
        # Update last timestamp
        if not new_candles.empty:
            self._last_ts[key] = new_candles["timestamp"].max()
        
        # Check if last candle is closed
        candle_closed = self._is_candle_closed(new_candles, tf_seconds)
        
        return self._cache[key], candle_closed, data_degraded
    
    def _update_cache(self, key: tuple, new_candles: pd.DataFrame) -> None:
        """Update cache with new candles."""
        if key in self._cache:
            existing = self._cache[key]
            combined = pd.concat([existing, new_candles], ignore_index=True)
            combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
            combined = combined.sort_values("timestamp").reset_index(drop=True)
            
            # Trim to max size
            if len(combined) > self.max_cache_size:
                combined = combined.iloc[-self.max_cache_size:]
            
            self._cache[key] = combined
        else:
            self._cache[key] = new_candles.iloc[-self.max_cache_size:]
    
    def _check_gaps(self, key: tuple, tf_seconds: int) -> bool:
        """Check for data gaps in cached candles."""
        if key not in self._cache:
            return True
        
        df = self._cache[key]
        if len(df) < 2:
            return False
        
        # Check consecutive timestamps
        timestamps = df["timestamp"].sort_values()
        expected_delta = timedelta(seconds=tf_seconds)
        
        for i in range(1, min(10, len(timestamps))):  # Check last 10 candles
            actual_delta = timestamps.iloc[-i] - timestamps.iloc[-i-1]
            if actual_delta > expected_delta * 1.5:  # Allow 50% tolerance
                logger.warning(f"Data gap detected for {key}: {actual_delta}")
                return True
        
        return False
    
    def _is_candle_closed(self, df: pd.DataFrame, tf_seconds: int) -> bool:
        """Check if the last candle is closed based on current time."""
        if df.empty:
            return False
        
        last_ts = df["timestamp"].max()
        now = datetime.now(timezone.utc)
        
        # Candle is closed if next candle start time has passed
        next_candle_start = last_ts + timedelta(seconds=tf_seconds)
        
        return now >= next_candle_start
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for CCXT."""
        # If already has slash, return as-is
        if "/" in symbol:
            return symbol
        
        # Common USDT pairs
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USDT"
        
        # Common USDC pairs
        if symbol.endswith("USDC"):
            base = symbol[:-4]
            return f"{base}/USDC"
        
        # Common BTC pairs
        if symbol.endswith("BTC"):
            base = symbol[:-3]
            return f"{base}/BTC"
        
        return symbol
    
    def get_cached_data(self, exchange: str, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached data for a subscription."""
        return self._cache.get((exchange, symbol, timeframe))
    
    def is_degraded(self, exchange: str, symbol: str, timeframe: str) -> bool:
        """Check if subscription data is degraded."""
        return (exchange, symbol, timeframe) in self._degraded
    
    def get_last_timestamp(self, exchange: str, symbol: str, timeframe: str) -> Optional[datetime]:
        """Get last fetched timestamp for a subscription."""
        return self._last_ts.get((exchange, symbol, timeframe))
    
    def clear_cache(self, exchange: str, symbol: str, timeframe: str) -> None:
        """Clear cache for a subscription."""
        key = (exchange, symbol, timeframe)
        self._cache.pop(key, None)
        self._last_ts.pop(key, None)
        self._degraded.discard(key)


class SubscriptionManager:
    """
    Manages multiple data subscriptions with scheduled updates.
    """
    
    def __init__(
        self,
        market_data: MarketDataService,
        poll_interval_multiplier: float = 0.9,
    ):
        self.market_data = market_data
        self.poll_multiplier = poll_interval_multiplier
        
        self._subscriptions: Dict[int, SubscriptionConfig] = {}
        self._tasks: Dict[int, asyncio.Task] = {}
        self._running = False
    
    def add_subscription(self, subscription: SubscriptionConfig) -> int:
        """Add a subscription and return its ID."""
        sub_id = subscription.id or len(self._subscriptions) + 1
        subscription.id = sub_id
        self._subscriptions[sub_id] = subscription
        return sub_id
    
    def remove_subscription(self, sub_id: int) -> bool:
        """Remove a subscription by ID."""
        if sub_id in self._subscriptions:
            del self._subscriptions[sub_id]
            if sub_id in self._tasks:
                self._tasks[sub_id].cancel()
                del self._tasks[sub_id]
            return True
        return False
    
    async def start(self, callback) -> None:
        """Start polling all subscriptions."""
        self._running = True
        
        for sub_id, sub in self._subscriptions.items():
            if sub.enabled:
                task = asyncio.create_task(self._poll_subscription(sub, callback))
                self._tasks[sub_id] = task
    
    async def stop(self) -> None:
        """Stop all polling tasks."""
        self._running = False
        
        for task in self._tasks.values():
            task.cancel()
        
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
    
    async def _poll_subscription(self, subscription: SubscriptionConfig, callback) -> None:
        """Poll a single subscription on schedule."""
        tf_seconds = timeframe_to_seconds(subscription.timeframe)
        poll_interval = tf_seconds * self.poll_multiplier
        
        # Minimum poll interval of 10 seconds
        poll_interval = max(10, poll_interval)
        
        while self._running:
            try:
                df, candle_closed, degraded = await self.market_data.update_subscription(
                    subscription
                )
                
                if not df.empty:
                    await callback(subscription, df, candle_closed, degraded)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error polling {subscription.symbol}: {e}")
            
            await asyncio.sleep(poll_interval)
