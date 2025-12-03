import asyncio
import logging
from typing import List, Dict, Optional, Any
import ccxt.async_support as ccxt
from datetime import datetime
import pandas as pd

from src.domain.interfaces import IDataFeed, IExecutionEngine
from src.domain.entities import Order, Trade, Position, MarketData, Side, OrderType, OrderStatus

logger = logging.getLogger(__name__)

class CCXTAdapter(IDataFeed, IExecutionEngine):
    """
    Adapter for CCXT exchanges. Supports Bybit, Zoomex, etc.
    Implements both IDataFeed and IExecutionEngine.
    """
    def __init__(self, exchange_id: str, api_key: str, api_secret: str, testnet: bool = False):
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.exchange: Optional[ccxt.Exchange] = None
        self._ws_clients = {} # Placeholder for direct WS if needed

    async def initialize(self):
        """Initialize the exchange connection."""
        exchange_class = getattr(ccxt, self.exchange_id)
        self.exchange = exchange_class({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # Perpetual swaps
            }
        })
        
        if self.testnet:
            self.exchange.set_sandbox_mode(True)
            
        # Load markets to ensure we have symbol details
        await self.exchange.load_markets()
        logger.info(f"Initialized CCXT adapter for {self.exchange_id} (Testnet: {self.testnet})")

    async def close(self):
        if self.exchange:
            await self.exchange.close()

    # -----------------------------------------------------------
    # IDataFeed Implementation
    # -----------------------------------------------------------
    async def subscribe(self, symbols: List[str]):
        # In a real CCXT Pro implementation, this would set up WS subscriptions.
        # For standard CCXT, we might just log this or start a polling loop.
        logger.info(f"Subscribing to {symbols} on {self.exchange_id}")
        pass

    async def get_historical_data(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")
            
        ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    # -----------------------------------------------------------
    # IExecutionEngine Implementation
    # -----------------------------------------------------------
    async def submit_order(self, order: Order) -> Order:
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")

        try:
            # Map internal enums to CCXT format
            side = order.side.value
            type_ = order.order_type.value
            
            params = {}
            if order.metadata:
                params.update(order.metadata)

            response = await self.exchange.create_order(
                symbol=order.symbol,
                type=type_,
                side=side,
                amount=order.quantity,
                price=order.price,
                params=params
            )
            
            # Update order with response data
            order.id = str(response['id'])
            order.status = self._map_status(response['status'])
            return order
            
        except Exception as e:
            logger.error(f"Error submitting order: {e}")
            order.status = OrderStatus.REJECTED
            return order

    async def cancel_order(self, order_id: str, symbol: str = None):
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")
        await self.exchange.cancel_order(order_id, symbol)

    async def get_positions(self) -> List[Position]:
        if not self.exchange:
            raise RuntimeError("Exchange not initialized")
            
        # Fetch positions (specifics vary by exchange, but CCXT unifies many)
        try:
            positions_raw = await self.exchange.fetch_positions()
            positions = []
            for p in positions_raw:
                if float(p['contracts']) > 0: # Only active positions
                    positions.append(Position(
                        symbol=p['symbol'],
                        side=Side.BUY if p['side'] == 'long' else Side.SELL,
                        quantity=float(p['contracts']),
                        entry_price=float(p['entryPrice']),
                        current_price=float(p['markPrice']),
                        unrealized_pnl=float(p['unrealizedPnl']),
                        timestamp=datetime.utcnow()
                    ))
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def _map_status(self, ccxt_status: str) -> OrderStatus:
        mapping = {
            'open': OrderStatus.NEW,
            'closed': OrderStatus.FILLED,
            'canceled': OrderStatus.CANCELED,
            'rejected': OrderStatus.REJECTED,
            'expired': OrderStatus.CANCELED
        }
        return mapping.get(ccxt_status, OrderStatus.CREATED)
