import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from .config import TradingBotConfig


class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings for structured logging.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)


def setup_logging(config: Optional[TradingBotConfig] = None) -> None:
    """
    Setup logging configuration based on the provided config.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console Handler (Human readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File Handler (JSON structured for analysis) - if configured or default
    # simplified for now, just always file log to 'bot.log'
    file_handler = logging.FileHandler("bot.json.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(file_handler)

    # Example of level adjustments based on config could go here
    # if config and config.debug:
    #     root_logger.setLevel(logging.DEBUG)

    logging.info("Logging initialized")
