import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def handle_exceptions(
    log_message: str = "Error executing function", reraise: bool = False
):
    """
    Decorator to handle exceptions in critical strategy methods.
    Logs the error and optionally reraises it.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.error(f"{log_message} ({func.__name__}): {e}", exc_info=True)
                if reraise:
                    raise
                return None

        return wrapper

    return decorator
