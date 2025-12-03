import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.exchange import ExchangeClient
from src.config import ExchangeConfig

@pytest.fixture
def mock_config():
    return ExchangeConfig(
        name="zoomex",
        testnet=True,
        api_key="test",
        secret_key="test",
        passphrase="test"
    )

@pytest.mark.asyncio
async def test_exchange_client_init(mock_config):
    mock_paper = MagicMock()
    client = ExchangeClient(mock_config, app_mode="paper", paper_broker=mock_paper)
    assert client.app_mode == "paper"
    assert client.paper_broker is not None

@pytest.mark.asyncio
async def test_cancel_all_orders_paper(mock_config):
    mock_paper = MagicMock()
    # Mock cancel_all_orders on paper broker to be async
    mock_paper.cancel_all_orders = AsyncMock()
    
    client = ExchangeClient(mock_config, app_mode="paper", paper_broker=mock_paper)
    # Should not raise error
    await client.cancel_all_orders("BTC/USDT")

@pytest.mark.asyncio
async def test_get_historical_data(mock_config):
    mock_paper = MagicMock()
    client = ExchangeClient(mock_config, app_mode="paper", paper_broker=mock_paper)
    # Mock paper broker to return a DataFrame
    import pandas as pd
    df_mock = pd.DataFrame({
        "timestamp": [1600000000000],
        "open": [100],
        "high": [101],
        "low": [99],
        "close": [100],
        "volume": [10]
    })
    mock_paper.get_historical_data = AsyncMock(return_value=df_mock)
    
    df = await client.get_historical_data("BTC/USDT", "1h")
    assert df is not None
    assert not df.empty
    assert "close" in df.columns
    assert df.iloc[0]["close"] == 100
