from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import ExchangeConfig
from src.exchange import create_exchange_client
from src.exchanges.paper_exchange import PaperExchange


@pytest.fixture
def mock_config():
    return ExchangeConfig(
        name="zoomex",
        testnet=True,
        api_key="test",
        secret_key="test",
        passphrase="test",
    )


@pytest.mark.asyncio
async def test_exchange_client_init(mock_config):
    mock_paper = MagicMock()
    with patch("src.exchanges.paper_exchange.CCXTClient"):
        client = create_exchange_client(
            mock_config, app_mode="paper", paper_broker=mock_paper
        )
        assert isinstance(client, PaperExchange)
        assert client.paper_broker is not None


@pytest.mark.asyncio
async def test_cancel_all_orders_paper(mock_config):
    mock_paper = MagicMock()
    mock_paper.cancel_all_orders = AsyncMock(return_value=[])

    with patch("src.exchanges.paper_exchange.CCXTClient"):
        client = create_exchange_client(
            mock_config, app_mode="paper", paper_broker=mock_paper
        )
        await client.cancel_all_orders("BTC/USDT")
        mock_paper.cancel_all_orders.assert_called_once()


@pytest.mark.asyncio
async def test_get_historical_data(mock_config):
    mock_paper = MagicMock()
    with patch("src.exchanges.paper_exchange.CCXTClient") as mock_ccxt_cls:
        mock_ccxt = AsyncMock()
        mock_ccxt_cls.return_value = mock_ccxt
        # Mock ccxt get_historical_data via exchange wrapper
        # (PaperExchange delegates to CCXTClient)
        import pandas as pd

        df_mock = pd.DataFrame(
            {
                "timestamp": [1600000000000],
                "open": [100],
                "high": [101],
                "low": [99],
                "close": [100],
                "volume": [10],
            }
        )
        mock_ccxt.get_historical_data.return_value = df_mock

        client = create_exchange_client(
            mock_config, app_mode="paper", paper_broker=mock_paper
        )
        df = await client.get_historical_data("BTC/USDT", "1h")
        assert df is not None
        assert not df.empty
        assert "close" in df.columns
        assert df.iloc[0]["close"] == 100
