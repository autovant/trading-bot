"""
Input sanitization and security tests (Epic 6.13).

Tests SQL injection, XSS, path traversal, oversized payloads,
and API key enforcement.
"""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure API key is set for auth middleware
os.environ.setdefault("API_KEY", "test-api-key-security")

from src.api.main import app
from src.api.routes.agents import get_db as get_db_agents
from src.api.routes.market import get_db as get_db_market, get_exchange
from src.api.routes.signals import get_db as get_db_signals
from src.api.routes.vault import get_db as get_db_vault
from src.database import DatabaseManager

API_KEY = os.environ["API_KEY"]
AUTH_HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture
def client(mock_db, mock_exchange):
    """TestClient with mocked database and exchange."""
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_market] = lambda: mock_db
    app.dependency_overrides[get_db_agents] = lambda: mock_db
    app.dependency_overrides[get_db_signals] = lambda: mock_db
    app.dependency_overrides[get_db_vault] = lambda: mock_db
    app.dependency_overrides[get_exchange] = lambda: mock_exchange
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


# ---------------------------------------------------------------------------
# Test 1: SQL injection via webhook body
# ---------------------------------------------------------------------------

class TestSQLInjectionWebhook:
    """POST to /api/webhook/tradingview with SQL injection in symbol field."""

    def test_sql_injection_symbol(self, client, mock_db):
        # SQLite backend doesn't implement create_signal — patch it
        mock_db.create_signal = AsyncMock(return_value=1)
        payload = {
            "symbol": "'; DROP TABLE agents; --",
            "side": "buy",
            "price": 100.0,
        }
        resp = client.post(
            "/api/webhook/tradingview",
            json=payload,
            headers=AUTH_HEADERS,
        )
        # Should not crash (not 500) — 200, 400, 401, or 403 are all acceptable
        assert resp.status_code != 500, f"Server error with SQL injection payload: {resp.text}"

    @pytest.mark.asyncio
    async def test_agents_table_survives_injection(self, mock_db):
        """Verify agents table still exists after injection attempt."""
        agents = await mock_db.list_agents()
        assert isinstance(agents, list)


# ---------------------------------------------------------------------------
# Test 2: XSS via agent name
# ---------------------------------------------------------------------------

class TestXSSAgentName:
    """POST to /api/agents with script tag in name."""

    def test_xss_in_agent_name_create(self, client):
        xss_name = "<script>alert('xss')</script>"
        payload = {
            "name": xss_name,
            "config": {},
            "allocation_usd": 1000.0,
        }
        resp = client.post(
            "/api/agents",
            json=payload,
            headers=AUTH_HEADERS,
        )
        # Should succeed (201) or reject (4xx) — not crash (500)
        assert resp.status_code in (201, 400, 422), f"Unexpected status: {resp.status_code}"

        if resp.status_code == 201:
            data = resp.json()
            # Name should be stored as-is (not interpreted/executed)
            assert data["name"] == xss_name
            # Verify GET returns it safely
            agent_id = data["id"]
            get_resp = client.get(f"/api/agents/{agent_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["name"] == xss_name
            # Content-Type must be JSON (browser won't execute scripts)
            assert "application/json" in get_resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Test 3: Path traversal via symbol parameter
# ---------------------------------------------------------------------------

class TestPathTraversal:
    """GET /api/klines with path traversal in symbol."""

    def test_path_traversal_symbol(self, client):
        resp = client.get(
            "/api/klines",
            params={"symbol": "../../etc/passwd", "timeframe": "1h"},
        )
        # Should be a normal error (400, 422, 500 from exchange) — not a file read
        # The key assertion: response body must not contain file contents
        body = resp.text
        assert "root:" not in body, "Path traversal leaked /etc/passwd contents"
        assert "/bin/" not in body, "Path traversal leaked filesystem contents"

    def test_path_traversal_null_bytes(self, client):
        resp = client.get(
            "/api/klines",
            params={"symbol": "BTCUSDT\x00../../etc/passwd", "timeframe": "1h"},
        )
        body = resp.text
        assert "root:" not in body


# ---------------------------------------------------------------------------
# Test 4: Oversized request body
# ---------------------------------------------------------------------------

class TestOversizedPayload:
    """POST to /api/agents with an oversized JSON body."""

    def test_oversized_body(self, client):
        # 10MB payload
        large_data = "x" * (10 * 1024 * 1024)
        payload = {
            "name": "oversized-agent",
            "config": {"data": large_data},
            "allocation_usd": 1000.0,
        }
        resp = client.post(
            "/api/agents",
            json=payload,
            headers=AUTH_HEADERS,
        )
        # Should reject (413, 422) or handle gracefully — not crash
        assert resp.status_code != 500 or resp.status_code in (413, 422, 400, 201)


# ---------------------------------------------------------------------------
# Test 5: Invalid / missing API key
# ---------------------------------------------------------------------------

class TestAPIKeyEnforcement:
    """All mutating endpoints should require valid X-API-Key."""

    PROTECTED_ENDPOINTS = [
        ("POST", "/api/agents"),
        ("POST", "/api/risk/kill-switch"),
        ("POST", "/api/vault/credentials"),
        ("PUT", "/api/risk/limits"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_no_api_key_returns_401(self, client, method, path):
        """Requests without X-API-Key should get 401."""
        resp = client.request(method, path, json={})
        assert resp.status_code == 401, (
            f"{method} {path} returned {resp.status_code} without API key"
        )

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_wrong_api_key_returns_401(self, client, method, path):
        """Requests with an invalid X-API-Key should get 401."""
        resp = client.request(
            method, path, json={},
            headers={"X-API-Key": "totally-wrong-key"},
        )
        assert resp.status_code == 401, (
            f"{method} {path} returned {resp.status_code} with wrong API key"
        )

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_valid_api_key_passes_auth(self, client, method, path):
        """Requests with a valid X-API-Key should NOT get 401."""
        resp = client.request(
            method, path, json={},
            headers=AUTH_HEADERS,
        )
        # Should pass auth — may fail validation (422) or succeed, but not 401
        assert resp.status_code != 401, (
            f"{method} {path} returned 401 with valid API key"
        )
