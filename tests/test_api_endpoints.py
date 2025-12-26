import pytest
import datetime
from fastapi.testclient import TestClient
from src.api.main import app
from src.api.routes.market import get_db, get_exchange

@pytest.fixture
def client(mock_db, mock_exchange):
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_exchange] = lambda: mock_exchange
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def test_get_account_summary(client, mock_exchange):
    async def get_balance():
        return 10000.0
    async def get_positions_mock():
        return [{"symbol": "BTC", "unrealized_pnl": 50.0, "cost": 100.0}]
    
    mock_exchange.get_balance.side_effect = get_balance
    mock_exchange.get_positions.side_effect = get_positions_mock
    
    response = client.get("/api/account")
    assert response.status_code == 200
    data = response.json()
    assert data["balance"] == 10000.0
    assert data["equity"] == 10050.0
    assert data["unrealized_pnl"] == 50.0

@pytest.mark.asyncio
async def test_get_positions(client):
    # Depending on mock_db state, this might return empty list.
    response = client.get("/api/positions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@pytest.mark.asyncio
async def test_get_trades(client):
    response = client.get("/api/trades")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@pytest.mark.asyncio
async def test_get_orders(client):
    response = client.get("/api/orders")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
