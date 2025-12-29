import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

RECV_WINDOW = "5000"


class ZoomexError(RuntimeError):
    pass


def _parse_server_time_ms(payload: Dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        raise ZoomexError("Unexpected time payload")
    if "timeSecond" in payload:
        return int(payload["timeSecond"]) * 1000
    if "timeNano" in payload:
        return int(int(payload["timeNano"]) / 1_000_000)
    if "time" in payload:
        return int(payload["time"])
    raise ZoomexError("Server time missing in response")


@dataclass
class Precision:
    qty_step: float
    min_qty: float


class ZoomexV3Client:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        category: str = "linear",
        max_retries: int = 3,
        mode_name: str = "live",
        require_auth: bool = True,
        max_requests_per_second: int = 5,
        max_requests_per_minute: int = 60,
    ) -> None:
        self.session = session
        default_base = "https://openapi.zoomex.com"
        self.base_url = base_url or os.getenv("ZOOMEX_BASE", default_base)
        self.api_key = api_key or os.getenv("ZOOMEX_API_KEY")
        self.api_secret = api_secret or os.getenv("ZOOMEX_API_SECRET")
        self.category = category
        self.max_retries = max_retries
        self.mode_name = mode_name

        self._max_requests_per_second = max_requests_per_second
        self._max_requests_per_minute = max_requests_per_minute
        self._last_request_time = 0.0
        self._request_count_minute = 0
        self._last_minute_start = time.time()
        self._time_offset_ms = 0
        self._last_time_sync = 0.0

        if require_auth and (not self.api_key or not self.api_secret):
            raise ValueError("ZOOMEX_API_KEY and ZOOMEX_API_SECRET must be set")

    @staticmethod
    def _ts_ms() -> str:
        return str(int(time.time() * 1000))

    def _ts_ms_with_offset(self) -> str:
        return str(int(time.time() * 1000 + self._time_offset_ms))

    def _sign(self, payload: str) -> str:
        message = f"{payload}".encode()
        if self.api_secret is None:
            raise ZoomexError("Zoomex API secret not configured")
        secret = self.api_secret.encode()
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    def _headers(self, payload: str) -> Dict[str, str]:
        if self.api_key is None:
            raise ZoomexError("Zoomex API key not configured")
        timestamp = self._ts_ms_with_offset()
        sign_payload = f"{timestamp}{self.api_key}{RECV_WINDOW}{payload}"
        signature = self._sign(sign_payload)
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Dict[str, Any]:
        await self._rate_limit()

        url = f"{self.base_url}{endpoint}"
        body = json.dumps(payload or {}, separators=(",", ":")) if payload else ""
        headers = {}

        if signed:
            sign_target = body
            headers = self._headers(sign_target)

        backoff = 1
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self.session.request(
                    method,
                    url,
                    headers=headers,
                    data=body if body else None,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        logger.error(f"HTTP {resp.status}: {text}")
                        if attempt < self.max_retries:
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue
                        raise ZoomexError(f"HTTP {resp.status}: {text}")
                    data = json.loads(text)
                    if data.get("retCode") != 0:
                        msg = data.get("retMsg", "Unknown error")
                        raise ZoomexError(f"API error: {msg}")
                    return data.get("result", {})
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Request failed (attempt {attempt}): {e}")
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
        raise ZoomexError("Zoomex request failed after retries")

    async def sync_time(self, *, server_time_ms: Optional[int] = None) -> int:
        if server_time_ms is None:
            payload = await self._request("GET", "/v3/public/time")
            server_time_ms = _parse_server_time_ms(payload)
        local_ms = int(time.time() * 1000)
        self._time_offset_ms = int(server_time_ms - local_ms)
        self._last_time_sync = time.time()
        return self._time_offset_ms

    @property
    def time_offset_ms(self) -> int:
        return int(self._time_offset_ms)

    @property
    def last_time_sync(self) -> float:
        return self._last_time_sync

    async def _rate_limit(self) -> None:
        now = time.time()

        elapsed_second = now - self._last_request_time
        per_second_interval = 1 / self._max_requests_per_second
        if elapsed_second < per_second_interval:
            sleep_time = per_second_interval - elapsed_second
            if sleep_time > 0:
                logger.debug(
                    "SAFETY_RATE_LIMIT: Sleeping %.3fs to respect per-second limit (sec=%d)",
                    sleep_time,
                    self._max_requests_per_second,
                )
                await asyncio.sleep(sleep_time)
            now = time.time()

        if now - self._last_minute_start >= 60:
            self._request_count_minute = 0
            self._last_minute_start = now

        if self._request_count_minute >= self._max_requests_per_minute:
            sleep_time = 60 - (now - self._last_minute_start)
            if sleep_time > 0:
                logger.debug(
                    "SAFETY_RATE_LIMIT: Sleeping %.3fs to respect per-minute limit (min=%d)",
                    sleep_time,
                    self._max_requests_per_minute,
                )
                await asyncio.sleep(sleep_time)
            self._request_count_minute = 0
            self._last_minute_start = time.time()
            now = time.time()

        self._last_request_time = now
        self._request_count_minute += 1

    async def get_klines(
        self,
        symbol: str,
        interval: str = "5",
        limit: int = 300,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Fetch klines for a symbol/interval. Optional start/end (ms) provide range
        filtering for historical backfills. Falls back to legacy linear route if
        the primary path is not available.
        """
        base_params = {
            "category": self.category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        param_variants = [base_params]
        if start is not None or end is not None:
            param_variants = []
            for start_key, end_key in (("startTime", "endTime"), ("start", "end")):
                params = base_params.copy()
                if start is not None:
                    params[start_key] = start
                if end is not None:
                    params[end_key] = end
                param_variants.append(params)

        endpoints = ["/v3/public/market/kline", "/v3/public/linear/kline"]
        payload: Optional[Dict[str, Any]] = None
        last_exc: Optional[Exception] = None

        for endpoint in endpoints:
            for params in param_variants:
                try:
                    payload = await self._request("GET", endpoint, params=params)
                    break
                except ZoomexError as exc:
                    last_exc = exc
                    level = logger.warning if "404" in str(exc) else logger.error
                    level(
                        "Kline request failed via %s%s params=%s: %s",
                        self.base_url,
                        endpoint,
                        params,
                        exc,
                    )
                    # Try the next param/endpoint variant on known path errors.
                    if start is None and end is None and "404" not in str(exc):
                        # Without range params, propagate unexpected errors immediately.
                        raise
            if payload is not None:
                break

        if payload is None:
            if last_exc:
                raise last_exc
            raise ZoomexError("Unexpected empty kline response")
        if "list" not in payload:
            raise ZoomexError("Unexpected kline payload")
        columns = ["start", "open", "high", "low", "close", "volume"]
        data = payload["list"]
        if not data:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(data, columns=columns)
        df["start"] = pd.to_datetime(df["start"].astype("int64"), unit="ms", utc=True)
        numeric_cols = ["open", "high", "low", "close", "volume"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        df.set_index("start", inplace=True)
        df.sort_index(inplace=True)
        return df

    async def set_leverage(
        self, symbol: str, buy: int = 1, sell: int = 1
    ) -> Dict[str, Any]:
        payload = {
            "category": self.category,
            "symbol": symbol,
            "buyLeverage": str(buy),
            "sellLeverage": str(sell),
        }
        return await self._request(
            "POST", "/v3/private/position/set-leverage", payload=payload, signed=True
        )

    async def get_wallet_balance(self) -> Dict[str, Any]:
        params = {"accountType": "CONTRACT"}
        return await self._request(
            "GET", "/v3/private/account/wallet/balance", params=params, signed=True
        )

    async def get_positions(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        params = {"category": self.category}
        if symbol:
            params["symbol"] = symbol
        return await self._request(
            "GET", "/v3/private/position/list", params=params, signed=True
        )

    async def get_instruments_info(
        self, symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        params = {"category": self.category}
        if symbol:
            params["symbol"] = symbol
        return await self._request(
            "GET", "/v3/public/market/instruments-info", params=params
        )

    async def get_precision(self, symbol: str) -> Precision:
        info = await self.get_instruments_info(symbol=symbol)
        if "list" not in info or not info["list"]:
            raise ZoomexError(f"No instrument info for {symbol}")
        item = info["list"][0]
        lot_size_filter = item.get("lotSizeFilter", {})
        qty_step = float(lot_size_filter.get("qtyStep", "0.001"))
        min_qty = float(lot_size_filter.get("minOrderQty", "0.001"))
        return Precision(qty_step=qty_step, min_qty=min_qty)

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: float,
        price: Optional[float] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        close_on_trigger: bool = False,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "category": self.category,
            "symbol": symbol,
            "side": side.capitalize(),
            "orderType": order_type,
            "qty": str(qty),
            "timeInForce": time_in_force,
        }
        if price is not None:
            payload["price"] = str(price)
        if reduce_only:
            payload["reduceOnly"] = True
        if close_on_trigger:
            payload["closeOnTrigger"] = True
        if stop_loss is not None:
            payload["stopLoss"] = str(stop_loss)
        if take_profit is not None:
            payload["takeProfit"] = str(take_profit)
        return await self._request(
            "POST", "/v3/private/order/create", payload=payload, signed=True
        )

    async def get_wallet_equity(self) -> float:
        balance_data = await self.get_wallet_balance()
        if "list" not in balance_data or not balance_data["list"]:
            raise ZoomexError("No wallet balance data")
        coin_list = balance_data["list"][0].get("coin", [])
        for coin in coin_list:
            if coin.get("coin") == "USDT":
                return float(coin.get("equity", "0"))
        raise ZoomexError("USDT equity not found in wallet")

    async def get_account_balance(self) -> Dict[str, Any]:
        return await self.get_wallet_balance()

    async def get_position_qty(self, symbol: str, position_idx: int) -> float:
        positions_data = await self.get_positions(symbol=symbol)
        if "list" not in positions_data:
            return 0.0
        for pos in positions_data["list"]:
            if pos.get("positionIdx") == position_idx:
                return abs(float(pos.get("size", "0")))
        return 0.0

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
        payload = {
            "category": self.category,
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": str(qty),
            "positionIdx": position_idx,
            "takeProfit": str(tp),
            "stopLoss": str(sl),
            "tpTriggerBy": trigger_by,
            "slTriggerBy": trigger_by,
            "orderLinkId": order_link_id,
        }
        return await self._request(
            "POST", "/v3/private/order/create", payload=payload, signed=True
        )

    async def close_position_reduce_only(
        self,
        *,
        symbol: str,
        qty: float,
        side: str,
        position_idx: int,
        order_link_id: str,
    ) -> Dict[str, Any]:
        payload = {
            "category": self.category,
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": str(qty),
            "positionIdx": position_idx,
            "reduceOnly": True,
            "orderLinkId": order_link_id,
        }
        return await self._request(
            "POST", "/v3/private/order/create", payload=payload, signed=True
        )

    async def get_margin_info(
        self, symbol: str, position_idx: Optional[int] = None
    ) -> Dict[str, Any]:
        positions_data = await self.get_positions(symbol=symbol)
        positions = (
            positions_data.get("list", []) if isinstance(positions_data, dict) else []
        )
        match = None
        for pos in positions:
            if symbol and pos.get("symbol") != symbol:
                continue
            if position_idx is not None and pos.get("positionIdx") != position_idx:
                continue
            match = pos
            break

        if not match:
            logger.info(
                "Margin info not found for symbol=%s positionIdx=%s (returned=%d)",
                symbol,
                position_idx,
                len(positions),
            )

        margin_ratio = float(match.get("marginRatio", "0")) if match else 0.0
        found = match is not None

        balance_data = await self.get_wallet_balance()
        available = 0.0
        if "list" in balance_data and balance_data["list"]:
            coin_list = balance_data["list"][0].get("coin", [])
            for coin in coin_list:
                if coin.get("coin") == "USDT":
                    available = float(coin.get("availableToWithdraw", "0"))
                    break

        return {
            "marginRatio": margin_ratio,
            "availableBalance": available,
            "found": found,
        }

    async def get_open_orders(self, symbol: str) -> Dict[str, Any]:
        params = {
            "category": self.category,
            "symbol": symbol,
            "openOnly": 1,
        }
        return await self._request(
            "GET", "/v3/private/order/realtime", params=params, signed=True
        )

    async def get_fills(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        params = {
            "category": self.category,
            "symbol": symbol,
            "limit": limit,
        }
        return await self._request(
            "GET", "/v3/private/execution/list", params=params, signed=True
        )

    async def get_closed_pnl(
        self, symbol: str, start_time: Optional[int] = None, limit: int = 50
    ) -> Dict[str, Any]:
        params = {
            "category": self.category,
            "symbol": symbol,
            "limit": limit,
        }
        if start_time:
            params["startTime"] = start_time
        return await self._request(
            "GET", "/v3/private/position/closed-pnl", params=params, signed=True
        )
