"""Structured JSON logging configuration with correlation ID middleware."""

from __future__ import annotations

import logging
import os
import uuid
from contextvars import ContextVar
from typing import Optional, Union

from fastapi import Request, Response
from pythonjsonlogger.json import JsonFormatter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .config import TradingBotConfig

# Context variable for request correlation ID
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class _CorrelationJsonFormatter(JsonFormatter):
    """JSON formatter that injects service name and correlation ID."""

    def __init__(self, service_name: str, **kwargs):
        super().__init__(**kwargs)
        self._service_name = service_name

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["service"] = self._service_name
        log_record["level"] = record.levelname
        req_id = correlation_id_var.get("")
        if req_id:
            log_record["request_id"] = req_id


def setup_logging(
    config_or_name: Union[Optional[TradingBotConfig], str] = None,
    level: str = "INFO",
) -> logging.Logger:
    """Configure the root logger with JSON structured output.

    Supports two call patterns:
    - ``setup_logging(config)`` — legacy, uses ``TradingBotConfig`` object
    - ``setup_logging("service-name", level="DEBUG")`` — new, explicit service name

    Returns the configured root logger.
    """
    if isinstance(config_or_name, str):
        service_name = config_or_name
    else:
        service_name = "trading-bot"

    effective_level = os.getenv("LOG_LEVEL", level).upper()

    formatter = _CorrelationJsonFormatter(
        service_name=service_name,
        fmt="%(timestamp)s %(level)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp"},
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(effective_level)

    logging.info("Logging initialized")
    return root


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that propagates or generates a correlation ID."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = correlation_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            correlation_id_var.reset(token)
