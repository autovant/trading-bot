import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
from src.exchanges.zoomex_v3 import ZoomexV3Client, ZoomexError, Precision


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def client(mock_session):
    with patch.dict("os.environ", {
        "ZOOMEX_API_KEY": "test_key",
        "ZOOMEX_API_SECRET": "test_secret"
    }):
        return ZoomexV3Client(mock_session)


def test_client_initialization(client):
    assert client.api_key == "test_key"
    assert client.api_secret == "test_secret"
    assert client.category == "linear"


def test_client_missing_credentials():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            ZoomexV3Client(MagicMock())


def test_sign(client):
    signature = client._sign("test_payload")
    assert isinstance(signature, str)
    assert len(signature) == 64


def test_headers(client):
    headers = client._headers("{}")
    assert "X-BAPI-API-KEY" in headers
    assert "X-BAPI-TIMESTAMP" in headers
    assert "X-BAPI-SIGN" in headers
    assert "X-BAPI-RECV-WINDOW" in headers
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_get_klines_success(client, mock_session):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(
        return_value=json.dumps(
            {
                "retCode": 0,
                "result": {
                    "list": [
                        ["1609459200000", "29000", "29500", "28500", "29200", "1000"],
                        ["1609459500000", "29200", "29600", "29000", "29400", "1200"],
                    ]
                },
            }
        )
    )
    mock_response.raise_for_status = MagicMock()
    
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    
    mock_session.request = MagicMock(return_value=mock_cm)
    
    df = await client.get_klines("BTCUSDT", "5", 100)
    
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


@pytest.mark.asyncio
async def test_request_api_error(client, mock_session):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(
        return_value=json.dumps(
            {
                "retCode": 10001,
                "retMsg": "Invalid parameter",
            }
        )
    )
    mock_response.raise_for_status = MagicMock()
    
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    
    mock_session.request = MagicMock(return_value=mock_cm)
    
    with pytest.raises(ZoomexError):
        await client.get_klines("INVALID", "5", 100)


def test_precision():
    prec = Precision(qty_step=0.01, min_qty=0.1)
    assert prec.qty_step == 0.01
    assert prec.min_qty == 0.1


@pytest.mark.asyncio
async def test_get_margin_info_filters_symbol_and_index(client):
    client.get_positions = AsyncMock(
        return_value={
            "list": [
                {"symbol": "BTCUSDT", "positionIdx": 0, "marginRatio": "0.50"},
                {"symbol": "SOLUSDT", "positionIdx": 1, "marginRatio": "0.25"},
            ]
        }
    )
    client.get_wallet_balance = AsyncMock(
        return_value={
            "list": [
                {
                    "coin": [
                        {
                            "coin": "USDT",
                            "availableToWithdraw": "12.34",
                        }
                    ]
                }
            ]
        }
    )

    info = await client.get_margin_info("SOLUSDT", position_idx=1)
    assert info["found"] is True
    assert info["marginRatio"] == pytest.approx(0.25)
    assert info["availableBalance"] == pytest.approx(12.34)


@pytest.mark.asyncio
async def test_get_margin_info_handles_missing_match(client, caplog):
    client.get_positions = AsyncMock(return_value={"list": []})
    client.get_wallet_balance = AsyncMock(
        return_value={
            "list": [
                {
                    "coin": [
                        {
                            "coin": "USDT",
                            "availableToWithdraw": "5.0",
                        }
                    ]
                }
            ]
        }
    )

    with caplog.at_level(logging.INFO):
        info = await client.get_margin_info("SOLUSDT", position_idx=2)

    assert info["found"] is False
    assert info["marginRatio"] == 0.0
    assert "symbol=SOLUSDT" in caplog.text
