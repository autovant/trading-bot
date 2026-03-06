import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

EXEMPT_PATHS = {"/health", "/metrics", "/ws", "/docs", "/openapi.json", "/redoc"}

_UNAUTHORIZED = JSONResponse(
    status_code=401,
    content={"error": True, "message": "Invalid or missing API key"},
)


def get_api_key() -> str | None:
    """Get the configured API key."""
    return os.getenv("API_KEY") or os.getenv("VAULT_MASTER_KEY")


def _validate_key(provided: str) -> bool:
    """Validate provided key against active key and grace-period key."""
    from src.api.routes.auth import rotation_state
    return rotation_state.is_valid(provided)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header on non-exempt endpoints."""

    async def dispatch(self, request: Request, call_next):
        # CORS preflight — always allow
        if request.method == "OPTIONS":
            return await call_next(request)

        # Exempt paths
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # Optional read-only exemption
        require_auth_for_reads = os.getenv(
            "REQUIRE_AUTH_FOR_READS", "false"
        ).lower() in ("true", "1", "yes")

        if request.method == "GET" and not require_auth_for_reads:
            return await call_next(request)

        # Validate API key
        expected_key = get_api_key()
        if not expected_key:
            logger.warning("No API key configured — denying request to %s", request.url.path)
            return _UNAUTHORIZED

        provided_key = request.headers.get("X-API-Key", "")
        if not provided_key or not _validate_key(provided_key):
            logger.warning("Invalid API key for %s %s", request.method, request.url.path)
            return _UNAUTHORIZED

        return await call_next(request)
