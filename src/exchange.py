"""
Exchange connectivity layer with support for production-grade paper trading.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import aiohttp
import pandas as pd
from pydantic import BaseModel

from .config import ExchangeConfig
from .paper_trader import PaperBroker

logger = logging.getLogger(__name__)

Mode = Literal["live", "paper", "replay"]
Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_market"]


class OrderResponse(BaseModel):
    """Order acknowledgement returned to upstream callers."""

    order_id: str
    client_id: str
    symbol: str
    side: Side
    order_type: str
    quantity: float
    price: Optional[float]
    status: str
    mode: Mode
    timestamp: datetime


class PositionSnapshot(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    percentage: float
    timestamp: datetime


class RateLimiter:
    """Simple sliding-window rate limiter for exchange requests."""

    def __init__(self, max_requests: int = 120, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self._requests: List[float] = []

    async def acquire(self) -> None:
        now = time.time()
        self._requests = [ts for ts in self._requests if now - ts < self.time_window]
        if len(self._requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self._requests[0])
            if sleep_time > 0:
                logger.warning("Rate limit reached, backing off for %.2fs", sleep_time)
                await asyncio.sleep(sleep_time)
        self._requests.append(now)


class ExchangeClient:
    """
    Multi-mode exchange client.

    * ``live``  → executes against Bybit REST API.
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
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter()

        if app_mode != "live" and self.paper_broker is None:
            raise ValueError("PaperBroker instance required for non-live modes")

        self.base_url = (
            "https://api-testnet.bybit.com"
            if config.testnet
            else "https://api.bybit.com"
        )

    async def initialize(self) -> None:
        if self.app_mode != "live":
            logger.info("Exchange client initialised in %s mode", self.app_mode)
            return

        try:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "TradingBot/1.0"},
            )
            await self._test_connection()
            logger.info("Connected to %s", self.base_url)
        except Exception as exc:
            logger.error("Failed to initialise live exchange client: %s", exc)
            raise

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

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
    ) -> OrderResponse:
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
            )

        # Guard: never allow paper/shadow code paths to send real orders.
        if self.app_mode == "live" and self.paper_broker is not None:
            logger.debug("Shadow broker present; live order will be shadowed.")

        payload: Dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "side": side.upper(),
            "orderType": order_type.upper(),
            "qty": str(quantity),
        }
        if price is not None:
            payload["price"] = str(price)
        if stop_price is not None:
            payload["triggerPrice"] = str(stop_price)
        if reduce_only:
            payload["reduceOnly"] = True

        response = await self._make_request(
            "POST", "/v5/order/create", payload, signed=True
        )
        if not response or response.get("retCode") != 0:
            raise RuntimeError(f"Live order rejected: {response}")

        result = response["result"]
        order_id = result.get("orderId")
        ack = OrderResponse(
            order_id=order_id,
            client_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status="pending",
            mode=self.app_mode,
            timestamp=datetime.utcnow(),
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

        return ack

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

        payload = {"category": "linear"}
        response = await self._make_request(
            "GET", "/v5/position/list", payload, signed=True
        )
        if not response or response.get("retCode") != 0:
            return []

        snapshots: List[PositionSnapshot] = []
        for item in response["result"]["list"]:
            if float(item["size"]) <= 0:
                continue
            if symbols and item["symbol"] not in symbols:
                continue
            snapshots.append(
                PositionSnapshot(
                    symbol=item["symbol"],
                    side=item["side"],
                    size=float(item["size"]),
                    entry_price=float(item["avgPrice"]),
                    mark_price=float(item["markPrice"]),
                    unrealized_pnl=float(item["unrealisedPnl"]),
                    percentage=(
                        float(item["unrealisedPnl"])
                        / float(item["positionValue"])
                        * 100
                        if float(item["positionValue"]) != 0
                        else 0.0
                    ),
                    timestamp=datetime.utcnow(),
                )
            )
        return snapshots

    async def get_account_balance(self) -> Optional[Dict]:
        if self.app_mode != "live":
            if not self.paper_broker:
                return None
            return await self.paper_broker.get_account_balance()

        payload = {"accountType": "UNIFIED"}
        response = await self._make_request(
            "GET", "/v5/account/wallet-balance", payload, signed=True
        )
        if not response or response.get("retCode") != 0:
            return None
        return response["result"]

    async def get_historical_data(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> Optional[pd.DataFrame]:
        if self.session is None:
            return None

        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": timeframe,
            "limit": limit,
        }
        response = await self._make_request(
            "GET", "/v5/market/kline", params, signed=False
        )
        if not response or response.get("retCode") != 0:
            return None
        records = response["result"]["list"]
        df = pd.DataFrame(
            [
                {
                    "timestamp": datetime.fromtimestamp(int(item[0]) / 1000),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
                for item in records
            ]
        )
        return df.sort_values("timestamp")

    async def get_ticker(self, symbol: str) -> Optional[Dict]:
        params = {"category": "linear", "symbol": symbol}
        response = await self._make_request(
            "GET", "/v5/market/tickers", params, signed=False
        )
        if not response or response.get("retCode") != 0:
            return None
        tickers = response["result"]["list"]
        return tickers[0] if tickers else None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _test_connection(self) -> None:
        response = await self._make_request("GET", "/v5/market/time", None, False)
        if not response or response.get("retCode") != 0:
            raise RuntimeError(f"Exchange connectivity check failed: {response}")

    def _generate_signature(self, timestamp: str, params: str) -> str:
        if not self.config.api_key or not self.config.secret_key:
            raise ValueError("API credentials required for signed requests")
        payload = timestamp + self.config.api_key + "5000" + params
        return hmac.new(
            self.config.secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        signed: bool = False,
    ) -> Optional[Dict]:
        if self.session is None:
            return None

        await self.rate_limiter.acquire()
        url = f"{self.base_url}{endpoint}"
        headers: Dict[str, str] = {}

        payload = None
        query = None

        if signed:
            timestamp = str(int(time.time() * 1000))
            params_str = ""
            if method == "GET" and params:
                params_str = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
                query = params
            elif method == "POST" and params:
                params_str = "".join([f"{k}{v}" for k, v in sorted(params.items())])
                payload = params
            signature = self._generate_signature(timestamp, params_str)
            headers.update(
                {
                    "X-BAPI-API-KEY": self.config.api_key or "",
                    "X-BAPI-SIGN": signature,
                    "X-BAPI-SIGN-TYPE": "2",
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": "5000",
                    "Content-Type": "application/json",
                }
            )
        else:
            if method == "GET":
                query = params
            else:
                payload = params

        try:
            if method == "GET":
                async with self.session.get(url, params=query, headers=headers) as resp:
                    return await resp.json()
            if method == "POST":
                async with self.session.post(
                    url, json=payload, headers=headers
                ) as resp:
                    return await resp.json()
        except Exception as exc:
            logger.error("HTTP %s %s failed: %s", method, endpoint, exc)
            return None
        return None
