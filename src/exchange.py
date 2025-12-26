"""
Exchange connectivity layer with support for production-grade paper trading.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import ExchangeConfig
from .exchanges.live_exchange import LiveExchange
from .exchanges.paper_exchange import PaperExchange
from .interfaces import IExchange
from .models import Mode
from .paper_trader import PaperBroker

logger = logging.getLogger(__name__)

# Legacy support / Type Alias
ExchangeClient = IExchange


def create_exchange_client(
    config: ExchangeConfig,
    app_mode: Mode,
    paper_broker: Optional[PaperBroker] = None,
) -> IExchange:
    """
    Factory to create the appropriate exchange client based on application mode.
    """
    if app_mode == "live":
        logger.info("Creating LiveExchange client")
        return LiveExchange(config)
    else:
        # Paper, Backtest, Replay
        if paper_broker is None:
            raise ValueError(f"PaperBroker required for mode {app_mode}")

        logger.info(f"Creating PaperExchange client for mode {app_mode}")
        return PaperExchange(config, paper_broker)
