import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

# Set the API key env var for testing
os.environ["API_KEY"] = "test-secret-key"

# We must mock dependencies BEFORE importing the app to avoid running initialization code that might fail
# However, we import app from src.api_server.
# We need to patch the DatabaseManager used in lifespan.


@pytest.fixture
def mock_dependencies():
    # We need to patch the classes imported in src.api_server
    # Note: StrategyService is not imported at top level in the snippet I saw,
    # but lifespan lines 561 init it. Let's find where it comes from.
    # It probably comes from src.services.strategy_service or similar?
    # I'll rely on global patching or just patch what is imported.
    # If StrategyService is not in imports, maybe it is defined in file?
    # No, likely imported.

    with (
        patch("src.api_server.DatabaseManager") as MockDB,
        patch("src.api_server.MessagingClient") as MockMsg,
        patch("src.api_server.ExchangeClient") as MockEx,
        patch("src.api_server.PaperBroker") as MockPaper,
        patch("src.api_server.StrategyService") as MockStrategy,
    ):
        # Setup AsyncMocks for awaitable methods
        MockDB.return_value.initialize = AsyncMock()
        MockDB.return_value.close = AsyncMock()
        MockDB.return_value.get_positions = AsyncMock(return_value=[])

        MockMsg.return_value.connect = AsyncMock()
        MockMsg.return_value.close = AsyncMock()
        MockMsg.return_value.publish = AsyncMock()

        MockEx.return_value.initialize = AsyncMock()
        MockEx.return_value.close = AsyncMock()

        # Strategy service might also need async mocks if called?
        # But we are testing api/mode which calls database.

        yield


def test_api_security(mock_dependencies):
    # Import app inside test function or after patching if possible.
    # Since patching is context manager, we must import inside or rely on patch finding the import.
    # But python imports are cached.
    # Better to import at top level, but assume patches work on the class.

    from src.api_server import app

    with TestClient(app) as client:
        # 1. Unprotected Endpoint (Health/Status)
        # Note: /api/bot/status calls get_bot_status() which uses global _config.
        # Ideally we should verify it returns 200, assuming config loads.
        resp = client.get("/api/bot/status")
        # Even if it errors 500 internally, it should NOT be 403.
        assert resp.status_code != status.HTTP_403_FORBIDDEN

        # 2. Protected Endpoint - No Key
        resp = client.post("/api/bot/start")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "Could not validate credentials" in resp.text

        # 3. Protected Endpoint - Wrong Key
        resp = client.post("/api/bot/start", headers={"X-API-KEY": "wrong-key"})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        # 4. Protected Endpoint - Correct Key
        # If the endpoint raises 500 (due to internal logic failing on mocks),
        # it means it PASSED the security check.
        resp = client.post("/api/bot/start", headers={"X-API-KEY": "test-secret-key"})
        assert resp.status_code != status.HTTP_403_FORBIDDEN

        # 5. Verify Mode Endpoint Security
        resp = client.post("/api/mode", json={"mode": "paper", "shadow": False})
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        resp = client.post(
            "/api/mode",
            json={"mode": "paper", "shadow": False},
            headers={"X-API-KEY": "test-secret-key"},
        )
        assert resp.status_code != status.HTTP_403_FORBIDDEN
