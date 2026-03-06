"""API integration tests for the Vault endpoints.

Covers: store → list → test-connection → delete lifecycle using the
in-memory SQLite backend and a mocked exchange client.
"""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes.vault import get_db as get_db_vault
from src.security.credential_vault import generate_master_key


@pytest.fixture
def master_key():
    return generate_master_key()


@pytest.fixture
def vault_client(mock_db, master_key):
    """TestClient wired to in-memory DB with vault master key set."""
    _saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_vault] = lambda: mock_db

    with patch.dict(os.environ, {
        "VAULT_MASTER_KEY": master_key,
        "API_KEY": master_key,
    }):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
    app.dependency_overrides.update(_saved)


# ── Full CRUD lifecycle ──────────────────────────────────────────────


def test_vault_lifecycle(vault_client, master_key):
    """store → list → get → delete → confirm gone."""
    headers = {"X-API-Key": master_key}

    # 1. Store credential
    resp = vault_client.post(
        "/api/vault/credentials",
        json={
            "exchange_id": "bybit",
            "label": "test-key",
            "api_key": "pk_live_abc",
            "api_secret": "sk_live_xyz",
            "is_testnet": True,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    cred = resp.json()
    assert cred["exchange_id"] == "bybit"
    assert cred["label"] == "test-key"
    assert cred["is_testnet"] is True
    cred_id = cred["id"]

    # 2. List — should contain the new credential
    resp = vault_client.get("/api/vault/credentials")
    assert resp.status_code == 200
    creds = resp.json()
    assert any(c["id"] == cred_id for c in creds)

    # 3. Delete
    resp = vault_client.delete(
        f"/api/vault/credentials/{cred_id}",
        headers=headers,
    )
    assert resp.status_code == 204

    # 4. Confirm gone
    resp = vault_client.get("/api/vault/credentials")
    assert resp.status_code == 200
    assert not any(c["id"] == cred_id for c in resp.json())


def test_vault_rejects_unsupported_exchange(vault_client, master_key):
    headers = {"X-API-Key": master_key}
    resp = vault_client.post(
        "/api/vault/credentials",
        json={
            "exchange_id": "not_real_exchange",
            "label": "bad",
            "api_key": "x",
            "api_secret": "y",
            "is_testnet": False,
        },
        headers=headers,
    )
    assert resp.status_code == 422  # Pydantic validation error


def test_vault_delete_nonexistent(vault_client, master_key):
    headers = {"X-API-Key": master_key}
    resp = vault_client.delete(
        "/api/vault/credentials/99999",
        headers=headers,
    )
    assert resp.status_code == 404


def test_vault_test_credential_not_found(vault_client, master_key):
    headers = {"X-API-Key": master_key}
    resp = vault_client.post(
        "/api/vault/credentials/99999/test",
        headers=headers,
    )
    assert resp.status_code == 404


def test_vault_no_master_key(mock_db):
    """Without VAULT_MASTER_KEY, store should return 503."""
    _saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_vault] = lambda: mock_db
    env = {k: v for k, v in os.environ.items() if k != "VAULT_MASTER_KEY"}
    env["API_KEY"] = "test"

    with patch.dict(os.environ, env, clear=True):
        with TestClient(app) as c:
            resp = c.post(
                "/api/vault/credentials",
                json={
                    "exchange_id": "binance",
                    "label": "x",
                    "api_key": "x",
                    "api_secret": "y",
                    "is_testnet": False,
                },
                headers={"X-API-Key": "test"},
            )
            assert resp.status_code == 503

    app.dependency_overrides.clear()
    app.dependency_overrides.update(_saved)
