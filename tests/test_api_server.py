import pytest
from fastapi.testclient import TestClient

from src.api_server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_list_presets(client):
    response = client.get("/api/presets")
    assert response.status_code == 200
    presets = response.json()
    assert isinstance(presets, list)
    assert len(presets) > 0
    assert "name" in presets[0]


def test_save_and_get_strategy(client):
    strategy_payload = {
        "name": "Test Strategy",
        "config": {
            "description": "A test strategy",
            "regime": {
                "timeframe": "1d",
                "indicators": [],
                "bullish_conditions": [],
                "bearish_conditions": [],
                "weight": 1.0,
            },
            "setup": {
                "timeframe": "4h",
                "indicators": [],
                "bullish_conditions": [],
                "bearish_conditions": [],
                "weight": 1.0,
            },
            "signals": [],
            "risk": {
                "stop_loss_type": "atr",
                "stop_loss_value": 1.0,
                "take_profit_type": "risk_reward",
                "take_profit_value": 2.0,
                "max_drawdown_limit": 0.1,
            },
            "confidence_threshold": 80,
        },
    }

    # Test validation
    response = client.post("/api/strategies", json={})
    assert response.status_code == 422

    # Save
    response = client.post("/api/strategies", json=strategy_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Strategy"

    # Get
    response = client.get("/api/strategies/Test Strategy")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Strategy"


def test_place_order(client):
    order_payload = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": 0.1,
        "price": 50000.0,
        "type": "limit",
    }

    response = client.post("/api/orders", json=order_payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_backtest_submission(client):
    payload = {"symbol": "BTCUSDT", "start": "2023-01-01", "end": "2023-01-02"}
    response = client.post("/api/backtests", json=payload)
    assert response.status_code == 202
    job = response.json()
    assert "job_id" in job
    assert job["status"] == "queued"
