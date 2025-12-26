"""
Shared FastAPI service scaffolding for Python microservices.

Each service extends :class:`BaseService` to gain consistent lifecycle
management, health/metrics endpoints, and clean shutdown semantics.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ..metrics import TRADING_MODE

logger = logging.getLogger(__name__)


class BaseService(ABC):
    """Abstract base class for FastAPI-powered services."""

    def __init__(self, name: str):
        self.name = name
        self._started = asyncio.Event()
        self._shutdown = asyncio.Event()

    async def start(self) -> None:
        logger.info("%s service starting", self.name)
        await self.on_startup()
        self._started.set()
        logger.info("%s service ready", self.name)

    async def stop(self) -> None:
        logger.info("%s service shutting down", self.name)
        await self.on_shutdown()
        self._shutdown.set()
        logger.info("%s service stopped", self.name)

    @property
    def started(self) -> asyncio.Event:
        return self._started

    def set_mode(self, mode: str) -> None:
        """Update Prometheus gauge for the active trading mode."""
        for candidate in ("live", "paper", "replay"):
            TRADING_MODE.labels(service=self.name, mode=candidate).set(
                1 if candidate == mode else 0
            )

    async def health(self) -> JSONResponse:
        """Return basic health information."""
        return JSONResponse(
            {
                "service": self.name,
                "status": "ok" if self._started.is_set() else "starting",
            }
        )

    async def metrics(self) -> Response:
        """Return Prometheus metrics payload."""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @abstractmethod
    async def on_startup(self) -> None:  # pragma: no cover - implemented by subclasses
        ...

    @abstractmethod
    async def on_shutdown(self) -> None:  # pragma: no cover - implemented by subclasses
        ...


def create_app(service: BaseService) -> FastAPI:
    """Create a FastAPI application wired to the provided service."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(title=f"{service.name.title()} Service", lifespan=lifespan)

    @app.get("/health")
    async def health_endpoint():
        return await service.health()

    @app.get("/metrics")
    async def metrics_endpoint():
        return await service.metrics()

    return app
