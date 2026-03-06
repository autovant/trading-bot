"""Tests for the credential vault (Epic 1.2.5).

Covers:
- Fernet key generation and validation
- Encrypt/decrypt round-trip
- Invalid key rejection
- Master key env var handling
- Vault API endpoints (create, list, delete, test connection)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient

from src.security.credential_vault import (
    generate_master_key,
    get_master_key,
    encrypt_credential,
    decrypt_credential,
)
from src.api.main import app
from src.api.routes.vault import get_db as get_db_vault


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def master_key():
    """A fresh Fernet key for each test."""
    return generate_master_key()


@pytest.fixture
def mock_db():
    """Mock DatabaseManager with async credential methods."""
    db = AsyncMock()
    db.store_credential = AsyncMock(return_value=1)
    db.get_credential = AsyncMock(return_value=None)
    db.list_credentials = AsyncMock(return_value=[])
    db.delete_credential = AsyncMock(return_value=True)
    return db


@pytest.fixture
def client(mock_db, master_key, monkeypatch):
    """TestClient with vault dependency overridden and auth configured."""
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("VAULT_MASTER_KEY", master_key)

    _saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_vault] = lambda: mock_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    app.dependency_overrides.update(_saved)


@pytest.fixture
def auth_headers(master_key, monkeypatch):
    """Headers including X-API-Key for mutating requests."""
    # Auth middleware accepts VAULT_MASTER_KEY as API key fallback
    monkeypatch.setenv("VAULT_MASTER_KEY", master_key)
    return {"X-API-Key": master_key}


# ---------------------------------------------------------------------------
# Unit tests — credential_vault module
# ---------------------------------------------------------------------------

class TestGenerateMasterKey:
    def test_generate_master_key(self):
        """Generated key is a valid Fernet key."""
        key = generate_master_key()
        assert isinstance(key, str)
        # Must not raise — valid Fernet key
        Fernet(key.encode("utf-8"))

    def test_generate_unique_keys(self):
        """Each call produces a distinct key."""
        keys = {generate_master_key() for _ in range(10)}
        assert len(keys) == 10


class TestEncryptDecryptRoundtrip:
    def test_encrypt_decrypt_roundtrip(self, master_key):
        """Encrypting then decrypting returns the original plaintext."""
        plaintext = "super-secret-api-key-12345"
        ciphertext = encrypt_credential(plaintext, master_key)
        assert ciphertext != plaintext
        assert decrypt_credential(ciphertext, master_key) == plaintext

    def test_encrypt_decrypt_empty_string(self, master_key):
        """Round-trip works for empty strings."""
        ciphertext = encrypt_credential("", master_key)
        assert decrypt_credential(ciphertext, master_key) == ""

    def test_encrypt_decrypt_unicode(self, master_key):
        """Round-trip preserves unicode characters."""
        plaintext = "pässwörd-日本語-🔑"
        ciphertext = encrypt_credential(plaintext, master_key)
        assert decrypt_credential(ciphertext, master_key) == plaintext

    def test_encrypt_different_values(self, master_key):
        """Different plaintexts produce different ciphertexts."""
        ct1 = encrypt_credential("key-alpha", master_key)
        ct2 = encrypt_credential("key-beta", master_key)
        assert ct1 != ct2

    def test_encrypt_same_value_produces_different_ciphertext(self, master_key):
        """Same plaintext encrypted twice gives different ciphertext (Fernet uses random IV)."""
        ct1 = encrypt_credential("same-value", master_key)
        ct2 = encrypt_credential("same-value", master_key)
        assert ct1 != ct2
        # Both still decrypt to the same plaintext
        assert decrypt_credential(ct1, master_key) == "same-value"
        assert decrypt_credential(ct2, master_key) == "same-value"


class TestDecryptWithWrongKey:
    def test_decrypt_with_wrong_key(self, master_key):
        """Decrypting with a different key raises InvalidToken."""
        ciphertext = encrypt_credential("secret", master_key)
        wrong_key = generate_master_key()
        assert wrong_key != master_key
        with pytest.raises(InvalidToken):
            decrypt_credential(ciphertext, wrong_key)


class TestGetMasterKey:
    def test_get_master_key_from_env(self, monkeypatch):
        """Returns the key when VAULT_MASTER_KEY is set."""
        monkeypatch.setenv("VAULT_MASTER_KEY", "test-key-value")
        assert get_master_key() == "test-key-value"

    def test_get_master_key_missing(self, monkeypatch):
        """Raises ValueError when VAULT_MASTER_KEY is not set."""
        monkeypatch.delenv("VAULT_MASTER_KEY", raising=False)
        with pytest.raises(ValueError, match="VAULT_MASTER_KEY"):
            get_master_key()

    def test_get_master_key_empty_string(self, monkeypatch):
        """Empty string is treated as missing."""
        monkeypatch.setenv("VAULT_MASTER_KEY", "")
        with pytest.raises(ValueError, match="VAULT_MASTER_KEY"):
            get_master_key()


# ---------------------------------------------------------------------------
# API tests — vault endpoints
# ---------------------------------------------------------------------------

class TestCreateCredentialAPI:
    def test_create_credential_api(self, client, mock_db, master_key):
        """POST /api/vault/credentials stores an encrypted credential."""
        mock_db.get_credential.return_value = {
            "id": 1,
            "exchange_id": "bybit",
            "label": "Main Account",
            "is_testnet": False,
            "created_at": "2026-01-01T00:00:00",
        }

        response = client.post(
            "/api/vault/credentials",
            json={
                "exchange_id": "bybit",
                "label": "Main Account",
                "api_key": "my-api-key",
                "api_secret": "my-api-secret",
                "is_testnet": False,
            },
            headers={"X-API-Key": master_key},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["exchange_id"] == "bybit"
        assert data["label"] == "Main Account"
        # Keys must never appear in the response
        assert "api_key" not in data
        assert "api_secret" not in data

        # Verify store_credential was called with encrypted values (not plaintext)
        call_kwargs = mock_db.store_credential.call_args
        assert call_kwargs is not None
        # The stored key should not be the plaintext
        assert call_kwargs.kwargs["api_key_enc"] != "my-api-key"
        assert call_kwargs.kwargs["api_secret_enc"] != "my-api-secret"
        # The stored values should be decryptable
        assert decrypt_credential(call_kwargs.kwargs["api_key_enc"], master_key) == "my-api-key"
        assert decrypt_credential(call_kwargs.kwargs["api_secret_enc"], master_key) == "my-api-secret"

    def test_unsupported_exchange(self, client, master_key):
        """POST with unsupported exchange is rejected with 422."""
        response = client.post(
            "/api/vault/credentials",
            json={
                "exchange_id": "fake_exchange",
                "label": "Bad",
                "api_key": "k",
                "api_secret": "s",
            },
            headers={"X-API-Key": master_key},
        )
        assert response.status_code == 422


class TestListCredentialsAPI:
    def test_list_credentials_api(self, client, mock_db):
        """GET /api/vault/credentials returns metadata list (no keys)."""
        mock_db.list_credentials.return_value = [
            {
                "id": 1,
                "exchange_id": "binance",
                "label": "Binance Prod",
                "is_testnet": False,
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": 2,
                "exchange_id": "bybit",
                "label": "Bybit Test",
                "is_testnet": True,
                "created_at": "2026-02-01T00:00:00",
            },
        ]

        response = client.get("/api/vault/credentials")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["exchange_id"] == "binance"
        assert data[1]["is_testnet"] is True
        # No secret data in response
        for item in data:
            assert "api_key" not in item
            assert "api_secret" not in item
            assert "api_key_enc" not in item
            assert "api_secret_enc" not in item


class TestDeleteCredentialAPI:
    def test_delete_credential_api(self, client, mock_db, master_key):
        """DELETE /api/vault/credentials/{id} removes the credential."""
        mock_db.get_credential.return_value = {
            "id": 1,
            "exchange_id": "kraken",
            "label": "Kraken",
            "is_testnet": False,
            "created_at": "2026-01-01T00:00:00",
        }

        response = client.delete(
            "/api/vault/credentials/1",
            headers={"X-API-Key": master_key},
        )
        assert response.status_code == 204
        mock_db.delete_credential.assert_awaited_once_with(1)

    def test_delete_nonexistent_credential(self, client, mock_db, master_key):
        """DELETE for missing credential returns 404."""
        mock_db.get_credential.return_value = None

        response = client.delete(
            "/api/vault/credentials/999",
            headers={"X-API-Key": master_key},
        )
        assert response.status_code == 404


class TestTestCredentialAPI:
    def test_test_credential_api(self, client, mock_db, master_key):
        """POST /api/vault/credentials/{id}/test decrypts and tests via ccxt."""
        # Store encrypted values in the mock credential row
        enc_key = encrypt_credential("live-api-key", master_key)
        enc_secret = encrypt_credential("live-api-secret", master_key)

        mock_db.get_credential.return_value = {
            "id": 1,
            "exchange_id": "bybit",
            "label": "Bybit Prod",
            "is_testnet": False,
            "api_key_enc": enc_key,
            "api_secret_enc": enc_secret,
            "passphrase_enc": None,
            "created_at": "2026-01-01T00:00:00",
        }

        mock_exchange_instance = MagicMock()
        mock_exchange_instance.fetch_balance = AsyncMock(return_value={"BTC": {"free": 1.0}})
        mock_exchange_instance.close = AsyncMock()

        with patch("src.api.routes.vault.ccxt") as mock_ccxt:
            mock_ccxt.bybit = MagicMock(return_value=mock_exchange_instance)
            response = client.post(
                "/api/vault/credentials/1/test",
                headers={"X-API-Key": master_key},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "bybit" in data["message"].lower()
        assert data["exchange_info"]["exchange"] == "bybit"

    def test_test_credential_auth_failure(self, client, mock_db, master_key):
        """Connection test returns success=false on AuthenticationError."""
        import ccxt as real_ccxt

        enc_key = encrypt_credential("bad-key", master_key)
        enc_secret = encrypt_credential("bad-secret", master_key)

        mock_db.get_credential.return_value = {
            "id": 1,
            "exchange_id": "binance",
            "label": "Binance",
            "is_testnet": False,
            "api_key_enc": enc_key,
            "api_secret_enc": enc_secret,
            "passphrase_enc": None,
            "created_at": "2026-01-01T00:00:00",
        }

        mock_exchange_instance = MagicMock()
        mock_exchange_instance.fetch_balance = AsyncMock(
            side_effect=real_ccxt.AuthenticationError("invalid key")
        )
        mock_exchange_instance.close = AsyncMock()

        with patch("src.api.routes.vault.ccxt") as mock_ccxt:
            mock_ccxt.binance = MagicMock(return_value=mock_exchange_instance)
            mock_ccxt.AuthenticationError = real_ccxt.AuthenticationError
            mock_ccxt.NetworkError = real_ccxt.NetworkError
            response = client.post(
                "/api/vault/credentials/1/test",
                headers={"X-API-Key": master_key},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "authentication" in data["message"].lower()

    def test_test_nonexistent_credential(self, client, mock_db, master_key):
        """Test connection for missing credential returns 404."""
        mock_db.get_credential.return_value = None

        response = client.post(
            "/api/vault/credentials/999/test",
            headers={"X-API-Key": master_key},
        )
        assert response.status_code == 404


class TestVaultWithoutMasterKey:
    def test_vault_without_master_key(self, mock_db, monkeypatch):
        """POST /api/vault/credentials returns 503 when VAULT_MASTER_KEY is not set."""
        monkeypatch.delenv("VAULT_MASTER_KEY", raising=False)
        monkeypatch.setenv("API_KEY", "test-api-key")

        _saved = dict(app.dependency_overrides)
        app.dependency_overrides[get_db_vault] = lambda: mock_db
        try:
            with TestClient(app) as c:
                response = c.post(
                    "/api/vault/credentials",
                    json={
                        "exchange_id": "bybit",
                        "label": "Bybit",
                        "api_key": "k",
                        "api_secret": "s",
                    },
                    headers={"X-API-Key": "test-api-key"},
                )
            assert response.status_code == 503
            body = response.json()
            # Error handler uses "message" key
            msg = body.get("message") or body.get("detail", "")
            assert "master key" in msg.lower()
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(_saved)
