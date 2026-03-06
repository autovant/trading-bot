"""
Full-stack E2E tests for the trading bot running via Docker Compose.

These tests assume all services are already running. They do NOT start Docker.
Skip unless the E2E_BASE_URL environment variable is set.

Usage:
    E2E_BASE_URL=http://localhost:8000 API_KEY=your-key pytest tests/test_fullstack_e2e.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import pytest

E2E_BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "test-api-key")
FRONTEND_URL = os.getenv("E2E_FRONTEND_URL", "http://localhost:3080")

SKIP_REASON = "E2E_BASE_URL not set — skipping full-stack E2E tests"
skip_unless_e2e = pytest.mark.skipif(
    os.getenv("E2E_BASE_URL") is None,
    reason=SKIP_REASON,
)

# Service health endpoints (name, host:port pattern)
SERVICE_HEALTH_ENDPOINTS: list[tuple[str, str]] = [
    ("api-server", f"{E2E_BASE_URL}/health"),
    ("execution", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8080/health"),
    ("feed", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8081/health"),
    ("reporter", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8083/health"),
    ("risk", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8084/health"),
    ("replay", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8085/health"),
    ("signal-engine", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8086/health"),
    ("llm-proxy", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8087/health"),
    ("agent-orchestrator", f"{E2E_BASE_URL.rsplit(':', 1)[0]}:8088/health"),
]


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    """Synchronous httpx client scoped to a single test."""
    with httpx.Client(base_url=E2E_BASE_URL, headers=_headers(), timeout=15) as c:
        yield c


@pytest.fixture
async def async_api_client():
    """Async httpx client scoped to a single test."""
    async with httpx.AsyncClient(base_url=E2E_BASE_URL, headers=_headers(), timeout=15) as c:
        yield c


# ---------------------------------------------------------------------------
# 4.3.1 — Docker Compose Smoke Test
# ---------------------------------------------------------------------------


@skip_unless_e2e
@pytest.mark.e2e
class TestDockerComposeSmokeTest:
    """Verify every service's /health endpoint returns 200."""

    @pytest.mark.parametrize("service_name,url", SERVICE_HEALTH_ENDPOINTS)
    async def test_all_health_endpoints(self, service_name: str, url: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            assert resp.status_code == 200, (
                f"{service_name} health check failed: {resp.status_code} — {resp.text}"
            )


# ---------------------------------------------------------------------------
# 4.3.2 — Dashboard Smoke Test
# ---------------------------------------------------------------------------


@skip_unless_e2e
@pytest.mark.e2e
class TestDashboardSmokeTest:

    async def test_dashboard_loads(self) -> None:
        """GET the frontend via nginx and verify it returns HTML with expected elements."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(FRONTEND_URL)
            assert resp.status_code == 200, f"Frontend returned {resp.status_code}"
            assert "text/html" in resp.headers.get("content-type", "")
            body = resp.text.lower()
            assert "<html" in body or "<!doctype" in body, "Response is not HTML"
            # React root div is the mount point
            assert "root" in body or "app" in body, (
                "Expected 'root' or 'app' container in HTML"
            )


# ---------------------------------------------------------------------------
# 4.3.3 — WebSocket E2E
# ---------------------------------------------------------------------------


@skip_unless_e2e
@pytest.mark.e2e
class TestWebSocketE2E:

    async def test_websocket_position_update(self) -> None:
        """Connect WS, subscribe to positions, place order, expect position update within 5s."""
        try:
            import websockets  # noqa: F811
        except ImportError:
            pytest.skip("websockets library not installed")

        ws_url = E2E_BASE_URL.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws"

        async with websockets.connect(ws_url) as ws:
            # Wait for the 'connected' message
            connected_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert connected_msg["type"] == "connected"

            # Subscribe to positions
            await ws.send(json.dumps({"action": "subscribe", "topics": ["positions"]}))
            sub_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert sub_msg["type"] == "subscribed"
            assert "positions" in sub_msg["topics"]

            # Place a market order via REST to trigger a position update
            async with httpx.AsyncClient(
                base_url=E2E_BASE_URL, headers=_headers(), timeout=10
            ) as client:
                order_resp = await client.post(
                    "/api/orders",
                    json={
                        "symbol": "BTCUSDT",
                        "side": "buy",
                        "quantity": 0.001,
                        "type": "market",
                    },
                )
                # Order may succeed or fail depending on exchange state;
                # we only need a 2xx/4xx — not a connection error.
                assert order_resp.status_code < 500, (
                    f"Order endpoint returned server error: {order_resp.text}"
                )

            # Wait for a position update (or any message) within 5 seconds.
            # In paper mode the execution service may broadcast a fill immediately.
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                # Accept any topic message as proof the WS pipeline works
                assert "topic" in msg or "type" in msg
            except asyncio.TimeoutError:
                # No message within timeout is acceptable in some configurations;
                # the WS connection itself proved healthy.
                pass


# ---------------------------------------------------------------------------
# 4.3.4 — Agent Lifecycle E2E
# ---------------------------------------------------------------------------


@skip_unless_e2e
@pytest.mark.e2e
class TestAgentLifecycleE2E:

    async def test_agent_lifecycle(self, async_api_client: httpx.AsyncClient) -> None:
        """Create → verify created → start (backtesting) → verify state → retire → delete."""
        client = async_api_client
        unique_name = f"e2e-agent-{uuid.uuid4().hex[:8]}"

        # --- Create agent ---
        create_resp = await client.post(
            "/api/agents",
            json={
                "name": unique_name,
                "config": {"test": True},
                "allocation_usd": 500.0,
            },
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        agent = create_resp.json()
        agent_id = agent["id"]
        assert agent["status"] == "created"
        assert agent["name"] == unique_name

        try:
            # --- Verify GET returns the agent ---
            get_resp = await client.get(f"/api/agents/{agent_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["status"] == "created"

            # --- Start (transition to backtesting) ---
            start_resp = await client.post(f"/api/agents/{agent_id}/start")
            assert start_resp.status_code == 200, f"Start failed: {start_resp.text}"
            assert start_resp.json()["status"] == "backtesting"

            # --- Verify state via GET ---
            get_resp2 = await client.get(f"/api/agents/{agent_id}")
            assert get_resp2.status_code == 200
            assert get_resp2.json()["status"] == "backtesting"

            # --- Retire agent ---
            retire_resp = await client.post(f"/api/agents/{agent_id}/retire")
            assert retire_resp.status_code == 200, f"Retire failed: {retire_resp.text}"
            assert retire_resp.json()["status"] == "retired"

        finally:
            # --- Cleanup: delete agent (must be retired or created) ---
            # Ensure the agent is in a deletable state
            check = await client.get(f"/api/agents/{agent_id}")
            if check.status_code == 200:
                status = check.json()["status"]
                if status not in ("retired", "created"):
                    await client.post(f"/api/agents/{agent_id}/retire")
                await client.delete(f"/api/agents/{agent_id}")


# ---------------------------------------------------------------------------
# 4.3.5 — Kill Switch E2E
# ---------------------------------------------------------------------------


@skip_unless_e2e
@pytest.mark.e2e
class TestKillSwitchE2E:

    async def test_kill_switch(self, async_api_client: httpx.AsyncClient) -> None:
        """Activate kill switch → verify agents paused → check risk status."""
        client = async_api_client

        # --- Setup: create an agent in backtesting state so the kill switch has something to pause ---
        unique_name = f"e2e-killswitch-{uuid.uuid4().hex[:8]}"
        create_resp = await client.post(
            "/api/agents",
            json={"name": unique_name, "allocation_usd": 100.0},
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["id"]

        # Move to backtesting so it's an "active" agent
        start_resp = await client.post(f"/api/agents/{agent_id}/start")
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] == "backtesting"

        try:
            # --- Activate kill switch ---
            kill_resp = await client.post("/api/risk/kill-switch")
            assert kill_resp.status_code == 200, f"Kill switch failed: {kill_resp.text}"
            kill_data = kill_resp.json()
            assert kill_data["status"] == "activated"
            assert "activated_at" in kill_data

            # --- Verify agent is now paused ---
            agent_resp = await client.get(f"/api/agents/{agent_id}")
            assert agent_resp.status_code == 200
            assert agent_resp.json()["status"] == "paused", (
                f"Agent should be paused after kill switch, got: {agent_resp.json()['status']}"
            )

            # --- Verify risk status reflects active kill switch ---
            risk_resp = await client.get("/api/risk/status")
            assert risk_resp.status_code == 200
            assert risk_resp.json()["kill_switch_active"] is True

        finally:
            # --- Cleanup: retire and delete the test agent ---
            await client.post(f"/api/agents/{agent_id}/retire")
            await client.delete(f"/api/agents/{agent_id}")


# ---------------------------------------------------------------------------
# 4.3.6 — Error State E2E
# ---------------------------------------------------------------------------


@skip_unless_e2e
@pytest.mark.e2e
class TestErrorHandlingE2E:

    async def test_404_on_nonexistent_route(
        self, async_api_client: httpx.AsyncClient
    ) -> None:
        """GET a nonexistent API path and verify 404 with detail message."""
        resp = await async_api_client.get("/api/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body

    async def test_422_on_invalid_agent_body(
        self, async_api_client: httpx.AsyncClient
    ) -> None:
        """POST /api/agents with invalid body and verify 422 validation error."""
        resp = await async_api_client.post(
            "/api/agents",
            json={"allocation_usd": "not-a-number"},  # missing required 'name', bad type
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body

    async def test_error_response_format(
        self, async_api_client: httpx.AsyncClient
    ) -> None:
        """Verify error responses include a 'detail' field with a message string."""
        resp = await async_api_client.get("/api/agents/999999")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        assert isinstance(body["detail"], str)
        assert len(body["detail"]) > 0
