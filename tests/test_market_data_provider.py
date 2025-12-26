from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.market_data_provider import MarketDataProvider


@pytest.fixture
def mock_exchange():
    exchange = AsyncMock()
    # Mock ccxt_client attribute if needed, essentially simulating LiveExchange behaviour partially
    # or just mocking IExchange methods
    return exchange


@pytest.mark.asyncio
async def test_get_ohlcv_delegation(mock_exchange):
    provider = MarketDataProvider(mock_exchange)

    mock_exchange.get_historical_data.return_value = "mock_data"

    data = await provider.get_ohlcv("BTC/USDT", "1h")
    assert data == "mock_data"
    mock_exchange.get_historical_data.assert_called_once_with("BTC/USDT", "1h", 200)


@pytest.mark.asyncio
async def test_get_ticker_missing_ccxt(mock_exchange):
    # If exchange does not have ccxt_client (like plain IExchange mock)
    # create a mock that DOES have it OR check that it returns None if not present
    del mock_exchange.ccxt_client

    provider = MarketDataProvider(mock_exchange)
    ticker = await provider.get_ticker("BTC/USDT")
    assert ticker is None  # Based on implementation returning None if attribute missing


@pytest.mark.asyncio
async def test_get_ticker_with_ccxt():
    mock_exch = MagicMock()
    mock_exch.ccxt_client = AsyncMock()
    mock_exch.ccxt_client.get_ticker.return_value = {"last": 50000}

    provider = MarketDataProvider(mock_exch)
    ticker = await provider.get_ticker("BTC/USDT")
    assert ticker == {"last": 50000}
