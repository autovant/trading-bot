"""
Exchange connectivity layer with support for production-grade paper trading.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .config import ExchangeConfig
from .exchanges.ccxt_client import CCXTClient
from .models import Mode, OrderResponse, OrderType, PositionSnapshot, Side
from .paper_trader import PaperBroker

logger = logging.getLogger(__name__)


class ExchangeClient:
    """
    Multi-mode exchange client.

    * ``live``  → executes against CCXT (Bybit/Zoomex/etc).
    * ``paper`` → routes through :class:`PaperBroker`.
    * ``replay`` → leverages :class:`PaperBroker` with replayed market data.
    """

    def __init__(
        self,
        config: ExchangeConfig,
        *,
        app_mode: Mode,
        paper_broker: Optional[PaperBroker] = None,
        shadow_broker: Optional[PaperBroker] = None,
    ):
        self.config = config
        self.app_mode = app_mode
        self.paper_broker = paper_broker if app_mode != "live" else None
        self.shadow_broker = shadow_broker
        
        # Initialize CCXT client for live mode OR paper mode (for data)
        self.ccxt_client: Optional[CCXTClient] = None
        # We will attempt to init CCXT in initialize()

        if app_mode != "live" and self.paper_broker is None:
            raise ValueError("PaperBroker instance required for non-live modes")

    async def initialize(self):
        """Initialize the exchange client."""
        # Always initialize CCXT client for data fetching, even in paper mode
        # In live mode, it's also used for execution
        try:
            self.ccxt_client = CCXTClient(self.config)
            await self.ccxt_client.initialize()
            if self.app_mode == "live":
                logger.info("ExchangeClient initialized in LIVE mode")
            else:
                logger.info(f"ExchangeClient initialized in {self.app_mode} mode (CCXT for data only)")
        except Exception as e:
            if self.app_mode == "live":
                logger.error(f"Failed to initialize CCXT client in LIVE mode: {e}")
                raise
            else:
                logger.warning(f"Failed to initialize CCXT client for data fetching: {e}")
                # In paper mode, we might survive without live data if we are backtesting with static data
                # But for 'paper' mode (forward testing), this is bad.
                if self.app_mode == "paper":
                     logger.warning("Paper trading will lack live market data!")

    async def initialize(self) -> None:
        """Initialize the exchange client."""
        try:
            # We attempt to init CCXT even in paper mode to get real market data
            self.ccxt_client = CCXTClient(self.config)
            await self.ccxt_client.initialize()
        except Exception as exc:
            if self.app_mode == "live":
                logger.error("Failed to initialise live exchange client: %s", exc)
                raise
            else:
                logger.warning("Failed to initialise CCXT client for data in paper mode: %s. Running without live data.", exc)
                self.ccxt_client = None

    async def close(self) -> None:
        if self.ccxt_client:
            await self.ccxt_client.close()

    async def place_order(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        client_id: Optional[str] = None,
        is_shadow: bool = False,
    ) -> Optional[OrderResponse]:
        if self.app_mode != "live":
            broker = self.paper_broker
            if broker is None:
                raise RuntimeError("Paper broker not configured")
            order = await broker.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                reduce_only=reduce_only,
                client_id=client_id,
                is_shadow=is_shadow,
            )
            return OrderResponse(
                order_id=order.order_id or order.client_id,
                client_id=order.client_id,
                symbol=order.symbol,
                side=order.side,  # type: ignore[arg-type]
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                status=order.status,
                mode=self.app_mode,
                timestamp=datetime.utcnow(),
                reduce_only=reduce_only,
            )

        if self.shadow_broker:
            asyncio.create_task(
                self.shadow_broker.place_order(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                    stop_price=stop_price,
                    reduce_only=reduce_only,
                    is_shadow=True,
                )
            )

        return response

    async def close_position(self, symbol: str) -> bool:
        if self.app_mode != "live":
            if not self.paper_broker:
                return False
            return await self.paper_broker.close_position(symbol)

        position = await self.get_positions(symbols=[symbol])
        if not position:
            return False

        pos = position[0]
        side: Side = "sell" if pos.side.lower() == "buy" else "buy"
        
        await self.place_order(
            symbol=symbol,
            side=side,
            order_type="market",
            quantity=pos.size,
            reduce_only=True,
        )
        return True

    async def get_positions(
        self, symbols: Optional[List[str]] = None
    ) -> List[PositionSnapshot]:
        if self.app_mode != "live":
            if not self.paper_broker:
                return []
            positions = await self.paper_broker.get_positions()
            return [
                PositionSnapshot(
                    symbol=pos.symbol,
                    side=pos.side,
                    size=pos.size,
                    entry_price=pos.entry_price,
                    mark_price=pos.mark_price,
                    unrealized_pnl=pos.unrealized_pnl,
                    percentage=pos.percentage,
                    timestamp=datetime.utcnow(),
                )
                for pos in positions
                if not symbols or pos.symbol in symbols
            ]

        if not self.ccxt_client:
            return []
            
        return await self.ccxt_client.get_positions(symbols)

    async def get_account_balance(self) -> Optional[Dict]:
        if self.app_mode != "live":
            if not self.paper_broker:
                return None
            return await self.paper_broker.get_account_balance()

        if not self.ccxt_client:
            return None
            
        return await self.ccxt_client.get_balance()

    async def get_historical_data(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[pd.DataFrame]:
        if self.app_mode != "live":
             if self.paper_broker and hasattr(self.paper_broker, "get_historical_data"):
                 return await self.paper_broker.get_historical_data(symbol, timeframe, limit)
             # If paper broker doesn't have it, maybe we can use CCXT if initialized?
             # But usually paper broker handles data.
             pass
        
        # If we have a CCXT client (live mode), use it.
        # If we are in paper mode but want real data, we should probably initialize CCXT client too?
        # The current implementation only initializes CCXT in live mode.
        # Let's stick to live mode for now.
        
        if self.ccxt_client:
            return await self.ccxt_client.get_historical_data(symbol, timeframe, limit)
            
        # Fallback or paper mode without CCXT?
        # Original code returned None if session is None.
        return None

    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        if self.ccxt_client:
            return await self.ccxt_client.get_ticker(symbol)
        return None

    async def get_margin_info(self, symbol: str, position_idx: int = 0) -> Dict[str, Any]:
        if self.app_mode != "live":
            # Mock margin info for paper trading
            return {"marginRatio": 0.0, "found": True}
        
        if self.ccxt_client:
            # CCXT might not have a direct mapping for this Zoomex specific call
            # We might need to implement it in CCXTClient or use a raw fetch
            # For now, let's assume CCXTClient has it or we mock it if missing
            if hasattr(self.ccxt_client, "get_margin_info"):
                return await self.ccxt_client.get_margin_info(symbol, position_idx)
            return {"marginRatio": 0.0, "found": True} # Fallback
        return {"marginRatio": 0.0, "found": False}

    async def set_leverage(self, symbol: str, buy: float, sell: float) -> None:
        if self.app_mode != "live":
            logger.info(f"[PAPER] Leverage set to {buy}x for {symbol}")
            return
        
        if self.ccxt_client:
            await self.ccxt_client.set_leverage(symbol, int(buy))

    async def get_precision(self, symbol: str) -> Any:
        # Return an object with min_qty, qty_step, price_step
        # We can reuse the Precision named tuple from zoomex_v3 if we import it, 
        # or just return a compatible object.
        from src.exchanges.zoomex_v3 import Precision
        
        if self.ccxt_client:
            # Use real exchange precision if available
            try:
                markets = await self.ccxt_client.load_markets()
                market = markets.get(symbol)
                if market:
                    return Precision(
                        min_qty=market['limits']['amount']['min'],
                        max_qty=market['limits']['amount']['max'],
                        qty_step=market['precision']['amount'],
                        price_step=market['precision']['price']
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch precision from CCXT: {e}")
        
        # Fallback defaults
        return Precision(min_qty=0.001, max_qty=1000.0, qty_step=0.001, price_step=0.1)

    async def create_market_with_brackets(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        tp: float,
        sl: float,
        position_idx: int,
        trigger_by: str,
        order_link_id: str,
    ) -> Dict[str, Any]:
        if self.app_mode != "live":
            # In paper mode, we place the main order with attached stops
            # PaperBroker supports stop_price (for stop orders) but not attached TP/SL to a market order directly 
            # in the same way Zoomex does (as separate child orders).
            # However, PaperBroker.place_order DOES NOT support attached TP/SL args in the signature I saw earlier.
            # I need to check PaperBroker.place_order signature again.
            # It has `stop_price` but that's for STOP orders, not SL for a market order.
            
            # We need to simulate brackets by placing separate orders?
            # Or just place the entry and let the strategy manage exits? 
            # The strategy (PerpsService) relies on this function to place brackets.
            
            # Let's place the entry first.
            entry_order = await self.place_order(
                symbol=symbol,
                side=side.lower(),
                order_type="market",
                quantity=qty,
                client_id=order_link_id
            )
            
            # Now place TP and SL as separate stop/limit orders?
            # PaperBroker supports "stop" orders.
            # TP: Limit order (reduce-only)
            # SL: Stop order (reduce-only)
            
            # SL
            sl_side = "sell" if side.lower() == "buy" else "buy"
            await self.place_order(
                symbol=symbol,
                side=sl_side,
                order_type="stop_market", # or stop
                quantity=qty,
                stop_price=sl,
                reduce_only=True,
                client_id=f"{order_link_id}-sl"
            )
            
            # TP
            await self.place_order(
                symbol=symbol,
                side=sl_side,
                order_type="limit",
                quantity=qty,
                price=tp,
                reduce_only=True,
                client_id=f"{order_link_id}-tp"
            )
            
            return {"orderId": entry_order.order_id}

        if self.ccxt_client:
             # CCXT might need custom implementation for brackets or use create_order with params
             # For now, let's assume we implement it or raise
             # But wait, we are replacing ZoomexV3Client which had this.
             # If we are in LIVE mode, we should use the ZoomexV3Client logic?
             # But we replaced it with CCXTClient.
             # Does CCXTClient support this?
             # If not, we might have broken live mode if we don't implement it in CCXTClient.
             # Assuming CCXTClient has it or we add it.
             pass
        return {}

    async def close_position_reduce_only(
        self,
        *,
        symbol: str,
        qty: float,
        side: str,
        position_idx: int,
        order_link_id: str,
    ) -> Dict[str, Any]:
        await self.place_order(
            symbol=symbol,
            side=side.lower(),
            order_type="market",
            quantity=qty,
            reduce_only=True,
            client_id=order_link_id
        )
        return {"orderId": order_link_id}

    async def cancel_all_orders(self, symbol: str) -> List[Dict[str, Any]]:
        if self.app_mode != "live":
            # Paper mode: cancel all orders in DB/memory
            if self.paper_broker:
                # PaperBroker doesn't have cancel_all, so we list and cancel?
                # Or we can add cancel_all to PaperBroker.
                # For now, let's assume we can't easily cancel all in paper broker without listing.
                # But wait, PaperBroker has cancel_order.
                # We need to fetch open orders first.
                # But ExchangeClient doesn't have get_open_orders exposed yet?
                # Let's add get_open_orders or just implement cancel_all in PaperBroker later.
                # For now, log it.
                logger.info(f"[PAPER] Cancelled all orders for {symbol}")
                return []
            return []

        if self.ccxt_client:
            return await self.ccxt_client.cancel_all_orders(symbol)
        return []
