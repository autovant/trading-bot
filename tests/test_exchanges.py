from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import get_config
from src.exchanges.live_exchange import LiveExchange
from src.exchanges.paper_exchange import PaperExchange
from src.paper_trader import PaperBroker


@pytest.fixture
def exchange_config():
    config = get_config()
    return config.exchange


@pytest.fixture
def paper_config():
    config = get_config()
    return config.paper


@pytest.fixture
def paper_broker(paper_config):
    # Mock database
    db = MagicMock()
    return PaperBroker(
        config=paper_config,
        database=db,
        mode="paper",
        run_id="test_run",
        initial_balance=10000.0,
    )


@pytest.mark.asyncio
async def test_live_exchange_initialization(exchange_config):
    with patch("src.exchanges.live_exchange.CCXTClient") as mock_ccxt_cls:
        mock_ccxt = AsyncMock()
        mock_ccxt_cls.return_value = mock_ccxt

        exchange = LiveExchange(exchange_config)
        await exchange.initialize()

        mock_ccxt.initialize.assert_called_once()
        assert exchange.config == exchange_config


@pytest.mark.asyncio
async def test_paper_exchange_initialization(exchange_config, paper_broker):
    with patch("src.exchanges.paper_exchange.CCXTClient") as mock_ccxt_cls:
        mock_ccxt = AsyncMock()
        mock_ccxt_cls.return_value = mock_ccxt

        exchange = PaperExchange(exchange_config, paper_broker)
        await exchange.initialize()

        # Should init CCXT for data
        mock_ccxt.initialize.assert_called_once()
        assert exchange.paper_broker == paper_broker


@pytest.mark.asyncio
async def test_paper_exchange_routing(exchange_config, paper_broker):
    """Test that execution calls route to paper_broker."""
    with patch("src.exchanges.paper_exchange.CCXTClient") as mock_ccxt_cls:
        paper_broker.place_order = AsyncMock(return_value={"id": "123"})
        paper_broker.get_account_balance = AsyncMock(return_value={"USDT": 1000})

        exchange = PaperExchange(exchange_config, paper_broker)

        # Test place_order
        await exchange.place_order(
            symbol="BTC/USDT", side="buy", order_type="limit", quantity=1.0, price=50000
        )
        paper_broker.place_order.assert_called_once()

        # Test get_balance
        await exchange.get_balance()
        paper_broker.get_account_balance.assert_called_once()


@pytest.mark.asyncio
async def test_live_exchange_routing(exchange_config):
    """Test that execution calls route to CCXT."""
    with patch("src.exchanges.live_exchange.CCXTClient") as mock_ccxt_cls:
        mock_ccxt = AsyncMock()
        mock_ccxt_cls.return_value = mock_ccxt

        exchange = LiveExchange(exchange_config)

        await exchange.place_order(
            symbol="BTC/USDT", side="buy", order_type="limit", quantity=1.0, price=50000
        )
        mock_ccxt.place_order.assert_called_once()
