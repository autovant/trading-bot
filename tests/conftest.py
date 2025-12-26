
import pytest
import asyncio
import os
from unittest.mock import MagicMock
from src.config import TradingBotConfig, DatabaseConfig, ExchangeConfig, get_config
from src.database import DatabaseManager
from src.exchange import ExchangeClient
from src.messaging import MessagingClient

@pytest.fixture
def test_config():
    """Create a test configuration."""
    conf = get_config()
    conf.app_mode = "paper"
    conf.database.url = "sqlite:///:memory:"
    # Use dummy creds for exchange to avoid validation errors
    conf.exchange.api_key = "test_key"
    conf.exchange.secret_key = "test_secret"
    return conf

@pytest.fixture
async def mock_db(test_config):
    """Create an in-memory database."""
    db = DatabaseManager(test_config.database)
    await db.initialize()
    yield db
    await db.close()

@pytest.fixture
def mock_exchange():
    """Create a mock exchange client."""
    exch = MagicMock(spec=ExchangeClient)
    exch.get_balance.return_value = {"USDT": 10000.0}
    exch.get_positions.return_value = []
    # Async mocks
    async def async_return(val=None):
        return val
    
    exch.initialize.side_effect = async_return
    exch.close.side_effect = async_return
    exch.place_order.side_effect = lambda **k: async_return({"order_id": "mock_oid", "status": "open"})
    return exch

@pytest.fixture
def mock_messaging():
    """Create a mock messaging client."""
    msg = MagicMock(spec=MessagingClient)
    async def async_return(val=None):
        return val
    msg.publish.side_effect = lambda s, m: async_return()
    msg.subscribe.side_effect = lambda s, c: async_return()
    return msg
