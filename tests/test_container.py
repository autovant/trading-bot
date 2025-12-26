from unittest.mock import AsyncMock, patch

import pytest

from src.config import get_config
from src.container import Container


@pytest.fixture
def test_config():
    return get_config()


@pytest.mark.asyncio
async def test_container_initialization(test_config):
    container = Container(test_config)

    # Mock everything that touches external world
    with (
        patch("src.container.DatabaseManager") as MockDB,
        patch("src.container.MessagingClient") as MockMsg,
        patch("src.container.PaperBroker") as MockPaper,
        patch("src.container.create_exchange_client") as MockCreateExchange,
        patch("src.container.TradingStrategy") as MockStrategy,
    ):
        mock_db_instance = AsyncMock()
        MockDB.return_value = mock_db_instance

        mock_msg_instance = AsyncMock()
        MockMsg.return_value = mock_msg_instance

        mock_exchange = AsyncMock()
        MockCreateExchange.return_value = mock_exchange

        mock_db_instance.list_strategies = AsyncMock(return_value=[])

        await container.initialize("test_run")

        assert container.database is not None
        mock_db_instance.initialize.assert_called_once()

        assert container.messaging is not None
        mock_msg_instance.connect.assert_called_once()

        assert container.exchange is not None
        mock_exchange.initialize.assert_called_once()

        assert container.strategy is not None


@pytest.mark.asyncio
async def test_container_shutdown(test_config):
    container = Container(test_config)
    container.exchange = AsyncMock()
    container.messaging = AsyncMock()
    container.session = AsyncMock()

    await container.shutdown()

    container.exchange.close.assert_called_once()
    container.messaging.close.assert_called_once()
    container.session.close.assert_called_once()
