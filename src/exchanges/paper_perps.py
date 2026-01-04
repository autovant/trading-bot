from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from ..config import ExchangeConfig, PerpsConfig
from ..models import MarketSnapshot
from ..paper_trader import PaperBroker
from .ccxt_client import CCXTClient
from .zoomex_v3 import Precision

logger = logging.getLogger(__name__)


class PaperPerpsExchange:
    """Paper-mode adapter for PerpsService using PaperBroker for execution."""

    def __init__(
        self,
        *,
        exchange_config: ExchangeConfig,
        perps_config: PerpsConfig,
        broker: PaperBroker,
        ccxt_client: Optional[CCXTClient] = None,
        spread_bps: float = 5.0,
    ) -> None:
        self.exchange_config = exchange_config
        self.perps_config = perps_config
        self.broker = broker
        self.ccxt_client = ccxt_client or CCXTClient(exchange_config)
        self._spread_bps = max(float(spread_bps), 0.0)
        self._initialized = False
        self._last_close_time: Dict[str, datetime] = {}

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        if not self.ccxt_client:
            return
        try:
            await self.ccxt_client.initialize()
        except Exception as exc:
            logger.warning("PaperPerpsExchange CCXT init failed: %s", exc)
            self.ccxt_client = None

    async def close(self) -> None:
        if self.ccxt_client:
            await self.ccxt_client.close()

    async def sync_time(self) -> int:
        return 0

    async def get_historical_data(
        self, *, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[pd.DataFrame]:
        if not self.ccxt_client:
            return pd.DataFrame()
        df = await self.ccxt_client.get_historical_data(
            symbol=symbol, timeframe=timeframe, limit=limit
        )
        if df is None or df.empty:
            return df
        if "timestamp" in df.columns:
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df.set_index("timestamp", inplace=True)
            df.sort_index(inplace=True)
        await self._update_snapshot_from_df(symbol, df)
        return df

    async def get_account_balance(self) -> Dict[str, Any]:
        return await self.broker.get_account_balance()

    async def get_wallet_balance(self) -> Dict[str, Any]:
        return await self.broker.get_account_balance()

    async def get_balance(self) -> Dict[str, Any]:
        return await self.broker.get_account_balance()

    async def get_positions(self, symbols: Optional[List[str]] = None) -> List[Any]:
        positions = await self.broker.get_positions()
        if not symbols:
            return positions
        wanted = {symbol.upper() for symbol in symbols}
        return [pos for pos in positions if pos.symbol.upper() in wanted]

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
        del position_idx, trigger_by
        entry_side = self._normalize_side(side)
        order = await self.broker.place_order(
            symbol=symbol,
            side=entry_side,
            order_type="market",
            quantity=qty,
            client_id=order_link_id,
        )
        exit_side = "sell" if entry_side == "buy" else "buy"
        if tp and tp > 0:
            await self.broker.place_order(
                symbol=symbol,
                side=exit_side,
                order_type="limit",
                quantity=qty,
                price=tp,
                reduce_only=True,
                client_id=f"{order_link_id}-tp",
            )
        if sl and sl > 0:
            await self.broker.place_order(
                symbol=symbol,
                side=exit_side,
                order_type="stop_market",
                quantity=qty,
                stop_price=sl,
                reduce_only=True,
                client_id=f"{order_link_id}-sl",
            )
        return {"orderId": order.order_id, "orderLinkId": order.client_id}

    async def close_position_reduce_only(
        self,
        *,
        symbol: str,
        qty: float,
        side: str,
        position_idx: int,
        order_link_id: str,
    ) -> Dict[str, Any]:
        del position_idx
        exit_side = self._normalize_side(side)
        order = await self.broker.place_order(
            symbol=symbol,
            side=exit_side,
            order_type="market",
            quantity=qty,
            reduce_only=True,
            client_id=order_link_id,
        )
        return {"orderId": order.order_id, "orderLinkId": order.client_id}

    async def cancel_all_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return await self.broker.cancel_all_orders(symbol)

    async def get_open_orders(self, symbol: str) -> Dict[str, Any]:
        orders = await self.broker.get_open_orders(symbol)
        payload = []
        for order in orders:
            if self._is_bracket_child(order.client_id):
                continue
            payload.append(
                {
                    "orderId": order.order_id or order.client_id,
                    "orderLinkId": order.client_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "qty": order.quantity,
                    "price": order.price,
                }
            )
        return {"list": payload}

    async def get_fills(self, symbol: str) -> Dict[str, Any]:
        trades = await self.broker.get_recent_trades(symbol)
        payload = []
        for trade in trades:
            ts = trade.timestamp or datetime.now(timezone.utc)
            payload.append(
                {
                    "orderId": trade.order_id,
                    "orderLinkId": trade.order_id,
                    "execId": trade.trade_id,
                    "execQty": trade.quantity,
                    "execPrice": trade.price,
                    "execFee": trade.fees,
                    "side": trade.side,
                    "symbol": trade.symbol,
                    "execTime": int(ts.timestamp() * 1000),
                }
            )
        return {"list": payload}

    async def get_closed_pnl(
        self, symbol: str, start_time: Optional[int] = None, limit: int = 50
    ) -> Dict[str, Any]:
        del start_time, limit
        trades = await self.broker.get_recent_trades(symbol)
        if not trades:
            return {"list": []}
        positions = await self.get_positions([symbol])
        if positions:
            return {"list": []}

        last_mark = self._last_close_time.get(symbol)
        ordered = sorted(
            trades, key=lambda trade: trade.timestamp or datetime.now(timezone.utc)
        )
        fresh = []
        for trade in ordered:
            ts = trade.timestamp or datetime.now(timezone.utc)
            if last_mark is None or ts > last_mark:
                fresh.append(trade)
        if not fresh:
            return {"list": []}

        total_pnl = sum(trade.realized_pnl for trade in fresh)
        latest_ts = fresh[-1].timestamp or datetime.now(timezone.utc)
        self._last_close_time[symbol] = latest_ts
        return {
            "list": [
                {
                    "symbol": symbol,
                    "closedPnl": total_pnl,
                    "createdTime": int(latest_ts.timestamp() * 1000),
                }
            ]
        }

    async def get_margin_info(
        self, symbol: str, position_idx: Optional[int] = None
    ) -> Dict[str, Any]:
        del symbol, position_idx
        balance = await self.broker.get_account_balance()
        available = float(balance.get("totalWalletBalance", 0.0))
        return {"marginRatio": 0.0, "availableBalance": available, "found": True}

    async def set_leverage(self, symbol: str, buy: int = 1, sell: int = 1) -> None:
        del symbol, buy, sell
        return None

    async def get_precision(self, symbol: str) -> Precision:
        del symbol
        return Precision(qty_step=0.001, min_qty=0.001)

    async def _update_snapshot_from_df(
        self, symbol: str, df: pd.DataFrame
    ) -> None:
        if df.empty:
            return
        close = float(df.iloc[-1]["close"])
        if close <= 0:
            return
        ts = df.index[-1]
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        spread = close * (self._spread_bps / 10_000)
        best_bid = max(close - spread / 2, 0.0)
        best_ask = close + spread / 2
        snapshot = MarketSnapshot(
            symbol=symbol,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=1.0,
            ask_size=1.0,
            last_price=close,
            timestamp=ts if isinstance(ts, datetime) else datetime.now(timezone.utc),
        )
        await self.broker.update_market(snapshot)

    @staticmethod
    def _normalize_side(side: str) -> str:
        return "buy" if str(side).lower().startswith("b") else "sell"

    @staticmethod
    def _is_bracket_child(client_id: Optional[str]) -> bool:
        if not client_id:
            return False
        return client_id.endswith("-tp") or client_id.endswith("-sl")
