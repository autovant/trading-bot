import logging
from typing import Union

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base exception for application specific errors."""

    def __init__(
        self, message: str, status_code: int = 500, details: Union[dict, str] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for all unhandled exceptions."""

    # Handle Application Errors
    if isinstance(exc, AppError):
        logger.warning(f"AppError: {exc.message} ({exc.status_code})")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": True, "message": exc.message, "details": exc.details},
        )

    # Handle Starlette/FastAPI HTTP Exceptions
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": True,
                "message": exc.detail,
            },
        )

    # Handle Validation Errors (Pydantic/FastAPI)
    if isinstance(exc, (RequestValidationError, ValidationError)):
        details = exc.errors() if hasattr(exc, "errors") else str(exc)
        logger.warning(f"Validation Error: {details}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": True, "message": "Validation Error", "details": details},
        )

    # Handle Unexpected Errors
    logger.error(f"Unexpected Error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "message": "Internal Server Error",
            "details": str(exc)
            if "prod" not in str(request.headers.get("mode", ""))
            else None,
        },
    )
