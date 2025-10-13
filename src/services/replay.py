"""
Market replay service implemented with FastAPI.

Streams historical OHLCV data as tick snapshots over NATS for replay
and shadow testing workflows.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from fastapi import Body, FastAPI, HTTPException
from nats.aio.msg import Msg
from nats.aio.subscription import Subscription

from ..config import TradingBotConfig, load_config
from ..messaging import MessagingClient
from .base import BaseService, create_app


class ReplayService(BaseService):
    """FastAPI wrapper around the paper trading replay stream."""

    def __init__(self) -> None:
        super().__init__("replay")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._control_sub: Optional[Subscription] = None
        self._running = asyncio.Event()
        self._dataset: List[Dict[str, float | str]] = []
        self._interval = 0.5
        self._last_control: Optional[str] = None
        self._last_control_at: Optional[datetime] = None

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        self.messaging = MessagingClient({"servers": self.config.messaging.servers})
        await self.messaging.connect()

        self._dataset = self._load_dataset()
        if not self._dataset:
            raise RuntimeError("Replay dataset is empty; check configuration")

        self._interval = self._derive_interval()
        self._running.set()

        control_subject = self.config.messaging.subjects.get(
            "replay_control", "replay.control"
        )
        self._control_sub = await self.messaging.subscribe(
            control_subject, self._handle_control
        )
        self._loop_task = asyncio.create_task(self._run_loop())

    async def on_shutdown(self) -> None:
        if self._control_sub:
            await self._control_sub.unsubscribe()
            self._control_sub = None

        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        if self.messaging:
            await self.messaging.close()
            self.messaging = None

        self._dataset = []

    async def _run_loop(self) -> None:
        assert self.config and self.messaging
        subject = self.config.messaging.subjects["market_data"]

        while True:
            for snapshot in self._dataset:
                await self._running.wait()
                await self.messaging.publish(subject, snapshot)
                await asyncio.sleep(self._interval)

    async def _handle_control(self, msg: Msg) -> None:
        try:
            payload = msg.data.decode("utf-8").strip().lower()
        except Exception:
            return

        if payload in {"pause", "resume"}:
            await self.set_state(payload)

    def _derive_interval(self) -> float:
        assert self.config is not None
        speed = self.config.replay.speed.lower()
        multiplier = 1
        if speed.endswith("x") and speed[:-1].isdigit():
            multiplier = max(int(speed[:-1]), 1)
        base_interval = 1.0  # seconds between ticks before speedup
        return max(base_interval / multiplier, 0.05)

    def _load_dataset(self) -> List[Dict[str, float | str]]:
        assert self.config is not None
        source = self.config.replay.source
        scheme, path = self._parse_source(source)
        dataset: List[Dict[str, float | str]] = []

        if scheme == "parquet":
            df = pd.read_parquet(path)
        elif scheme == "csv":
            df = pd.read_csv(path)
        else:
            df = (
                pd.read_parquet(path)
                if path.suffix == ".parquet"
                else pd.read_csv(path)
            )

        if "timestamp" not in df.columns:
            raise ValueError("Replay dataset must include a 'timestamp' column")

        df = df.sort_values("timestamp")

        for _, row in df.iterrows():
            ts = self._coerce_timestamp(row["timestamp"])
            symbol = row.get("symbol", self.config.trading.symbols[0])
            open_price = float(row.get("open", row.get("close", 0)))
            high = float(row.get("high", open_price))
            low = float(row.get("low", open_price))
            close = float(row.get("close", open_price))
            volume = float(row.get("volume", 1))
            snapshot = self._build_snapshot(
                symbol, ts, open_price, high, low, close, volume
            )
            dataset.append(snapshot)

        return dataset

    @staticmethod
    def _coerce_timestamp(value) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            # assume seconds
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return datetime.utcnow()

    @staticmethod
    def _parse_source(source: str) -> Tuple[str, Path]:
        if "://" in source:
            scheme, path = source.split("://", 1)
            return scheme.lower(), Path(path).expanduser().resolve()
        return "", Path(source).expanduser().resolve()

    @staticmethod
    def _build_snapshot(
        symbol: str,
        timestamp: datetime,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> Dict[str, float | str]:
        spread = max((high - low) * 0.2, max(close * 0.0004, 0.5))
        best_bid = close - spread / 2
        best_ask = close + spread / 2
        bid_size = max(volume * 0.25, 1)
        ask_size = max(volume * 0.25, 1)
        side = "buy" if close >= open_price else "sell"
        last_size = max(volume * 0.1, 1)
        ofi = (bid_size - ask_size) * spread

        return {
            "symbol": symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "last_price": close,
            "last_side": side,
            "last_size": last_size,
            "funding_rate": 0.0,
            "timestamp": timestamp.isoformat(),
            "order_flow_imbalance": ofi,
        }

    @property
    def state(self) -> str:
        return "running" if self._running.is_set() else "paused"

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def dataset_size(self) -> int:
        return len(self._dataset)

    @property
    def last_control(self) -> Optional[str]:
        return self._last_control

    @property
    def last_control_at(self) -> Optional[str]:
        if self._last_control_at is None:
            return None
        return self._last_control_at.isoformat()

    async def set_state(self, action: str) -> None:
        normalized = action.lower()
        if normalized == "pause":
            self._running.clear()
        elif normalized == "resume":
            self._running.set()
        else:
            raise ValueError(f"Unsupported replay control action: {action}")
        self._last_control = normalized
        self._last_control_at = datetime.now(timezone.utc)

    def status_payload(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "interval": self._interval,
            "dataset_size": self.dataset_size,
            "speed": getattr(self.config.replay, "speed", None)
            if self.config
            else None,
            "last_control": self._last_control,
            "last_control_at": self.last_control_at,
        }


service = ReplayService()
app: FastAPI = create_app(service)


@app.get("/status")
async def replay_status() -> Dict[str, Any]:
    return service.status_payload()


@app.post("/control")
async def replay_control(action: str = Body(..., embed=True)) -> Dict[str, Any]:
    try:
        await service.set_state(action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return service.status_payload()
