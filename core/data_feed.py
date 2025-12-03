import asyncio
import ccxt.pro as ccxtpro
import logging
from typing import List, Callable, Awaitable

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MarketStream")

class MarketStream:
    def __init__(self, exchange_id: str = 'binance', symbols: List[str] = None):
        self.exchange_id = exchange_id
        self.symbols = symbols or ['BTC/USDT']
        self.exchange = getattr(ccxtpro, exchange_id)()
        self.queue = asyncio.Queue()
        self.running = False

    async def start(self):
        """Start the market data stream."""
        self.running = True
        logger.info(f"Starting MarketStream for {self.symbols}")
        
        # Start OHLCV stream
        await self._stream_ohlcv()

    async def stop(self):
        """Stop the market data stream."""
        self.running = False
        await self.exchange.close()
        logger.info("MarketStream stopped")

    async def _stream_ohlcv(self):
        """Stream OHLCV data from CCXT Pro."""
        while self.running:
            try:
                # Watch OHLCV for all symbols (1 minute timeframe)
                # Note: ccxt.pro watch_ohlcv might handle one symbol at a time depending on exchange
                # We will loop through symbols or use watch_ohlcv_for_symbols if available
                
                # For simplicity in this loop, we'll focus on the first symbol or manage tasks
                # In a full prod env, we'd spawn tasks for each symbol
                
                for symbol in self.symbols:
                    candles = await self.exchange.watch_ohlcv(symbol, '1m')
                    latest_candle = candles[-1]
                    
                    update = {
                        'type': 'candle',
                        'symbol': symbol,
                        'data': {
                            'timestamp': latest_candle[0],
                            'open': latest_candle[1],
                            'high': latest_candle[2],
                            'low': latest_candle[3],
                            'close': latest_candle[4],
                            'volume': latest_candle[5]
                        }
                    }
                    
                    await self.queue.put(update)
                    # logger.debug(f"Pushed update for {symbol}")

            except Exception as e:
                logger.error(f"Stream error: {e}")
                await asyncio.sleep(5) # Backoff on error

    async def get_latest(self):
        """Get the next update from the queue."""
        return await self.queue.get()
