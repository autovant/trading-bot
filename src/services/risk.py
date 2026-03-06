"""
Risk state publisher implemented with FastAPI.

Computes real risk metrics from database positions and PnL, then publishes
to downstream consumers (strategy, dashboard) at a fixed cadence.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI

from ..config import TradingBotConfig, load_config
from ..database import DatabaseManager
from ..messaging import MessagingClient
from ..metrics import CIRCUIT_BREAKERS
from .base import BaseService, create_app

logger = logging.getLogger(__name__)


class RiskService(BaseService):
    """Real risk-state publisher derived from database positions and PnL."""

    def __init__(self) -> None:
        super().__init__("risk")
        self.config: Optional[TradingBotConfig] = None
        self.messaging: Optional[MessagingClient] = None
        self._task: Optional[asyncio.Task] = None
        self.database: Optional[DatabaseManager] = None
        self._run_id: Optional[str] = None
        self._peak_equity: float = 0.0
        self._consecutive_losses: int = 0
        self._crisis: bool = False

    async def on_startup(self) -> None:
        self.config = load_config()
        self.set_mode(self.config.app_mode)

        self.database = DatabaseManager(self.config.database.url)
        await self.database.initialize()
        self._run_id = (
            f"{self.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )

        self.messaging = MessagingClient({"servers": self.config.messaging.servers})
        await self.messaging.connect()

        self._task = asyncio.create_task(self._run())

    async def on_shutdown(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self.messaging:
            await self.messaging.close()
            self.messaging = None

        if self.database:
            await self.database.close()
            self.database = None

    async def _run(self) -> None:
        if self.config is None or self.messaging is None or self.database is None:
            raise RuntimeError("RiskService started before initialisation")
        subject = self.config.messaging.subjects["risk"]
        mode = self.config.app_mode

        while True:
            # --- Compute real metrics from DB ---
            drawdown = 0.0
            position_factor = 1.0

            # Get recent PnL to compute drawdown and consecutive losses
            try:
                pnl_history = await self.database.get_pnl_history(days=30)
                if pnl_history:
                    # Track peak equity from balance column
                    latest_balance = pnl_history[0].balance if pnl_history else 0.0
                    for entry in pnl_history:
                        if entry.balance > self._peak_equity:
                            self._peak_equity = entry.balance

                    if self._peak_equity > 0:
                        drawdown = max(0.0, (self._peak_equity - latest_balance) / self._peak_equity)

                    # Count consecutive losses from most recent entries
                    losses = 0
                    for entry in pnl_history:
                        if entry.net_pnl < 0:
                            losses += 1
                        else:
                            break
                    self._consecutive_losses = losses
            except Exception as exc:
                logger.debug("PnL query failed (ok on first run): %s", exc)

            # Get open positions to compute exposure-based position factor
            try:
                positions = await self.database.get_positions(mode=mode, run_id=self._run_id)
                if positions and self._peak_equity > 0:
                    total_exposure = sum(abs(p.size * p.mark_price) for p in positions)
                    exposure_ratio = total_exposure / self._peak_equity
                    # Scale factor: full size at <50% exposure, reduced above
                    position_factor = max(0.1, 1.0 - max(0.0, exposure_ratio - 0.5))
            except Exception as exc:
                logger.debug("Position query failed (ok on first run): %s", exc)

            # Crisis mode: triggered by excessive drawdown or consecutive losses
            previous_crisis = self._crisis
            crisis_threshold = self.config.risk.get("crisis_drawdown", 0.10) if hasattr(self.config, "risk") and isinstance(getattr(self.config, "risk", None), dict) else 0.10
            loss_threshold = 5

            if drawdown >= crisis_threshold or self._consecutive_losses >= loss_threshold:
                self._crisis = True
            elif drawdown < crisis_threshold * 0.5 and self._consecutive_losses < loss_threshold // 2:
                self._crisis = False

            if self._crisis and not previous_crisis:
                CIRCUIT_BREAKERS.labels(mode=mode).inc()
                logger.warning("Crisis mode ACTIVATED: drawdown=%.2f%%, consecutive_losses=%d",
                               drawdown * 100, self._consecutive_losses)
            elif not self._crisis and previous_crisis:
                logger.info("Crisis mode deactivated")

            payload = {
                "crisis_mode": self._crisis,
                "consecutive_losses": self._consecutive_losses,
                "drawdown": round(drawdown, 6),
                "volatility": 0.0,  # Populated by downstream market data consumers
                "position_size_factor": round(position_factor, 4),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await self.messaging.publish(subject, payload)

            if self._run_id and hasattr(self.database, "record_risk_snapshot"):
                try:
                    await self.database.record_risk_snapshot(
                        payload, mode=mode, run_id=self._run_id
                    )
                except Exception as exc:
                    logger.error("Failed to persist risk snapshot: %s", exc)

            await asyncio.sleep(5.0)


service = RiskService()
app: FastAPI = create_app(service)
