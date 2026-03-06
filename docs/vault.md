# Credential Vault

Secure storage for exchange API credentials with encryption at rest.

## Overview

The credential vault encrypts exchange API keys, secrets, and passphrases using Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256 for authentication). Credentials are stored encrypted in PostgreSQL and decrypted only when needed for exchange connectivity tests.

Relevant source files:
- `src/security/credential_vault.py` — encryption/decryption functions
- `src/api/routes/vault.py` — CRUD endpoints for credentials
- `src/api/routes/auth.py` — API key rotation with grace period

---

## Setup

### 1. Generate a Master Key

```bash
python -c "from src.security.credential_vault import generate_master_key; print(generate_master_key())"
```

This outputs a Fernet-compatible base64-encoded key.

### 2. Set the Environment Variable

Add to your `.env` file:

```bash
VAULT_MASTER_KEY=<generated-key>
```

### 3. Restart Services

```bash
docker compose up -d --no-deps api-server
```

If `VAULT_MASTER_KEY` is not set, vault endpoints return `503 Service Unavailable`.

---

## Supported Exchanges

The vault validates exchange IDs against the following supported list (must match [CCXT](https://github.com/ccxt/ccxt) exchange identifiers):

| Exchange ID | Name |
|-------------|------|
| `bybit` | Bybit |
| `binance` | Binance |
| `okx` | OKX |
| `coinbase` | Coinbase |
| `kraken` | Kraken |
| `bitget` | Bitget |
| `kucoin` | KuCoin |
| `gate` | Gate.io |
| `htx` | HTX (Huobi) |

---

## API Endpoints

All endpoints require the `X-API-Key` header.

### Store Credentials

```bash
curl -X POST http://localhost:8000/api/vault/credentials \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "exchange_id": "bybit",
    "label": "Main Bybit Account",
    "api_key": "your-api-key",
    "api_secret": "your-api-secret",
    "passphrase": null,
    "is_testnet": false
  }'
```

**Response** (`201 Created`):
```json
{
  "id": 1,
  "exchange_id": "bybit",
  "label": "Main Bybit Account",
  "is_testnet": false,
  "created_at": "2026-03-05T12:00:00Z"
}
```

The `api_key`, `api_secret`, and `passphrase` fields are encrypted before storage and never returned by any endpoint.

### List Credentials

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/vault/credentials
```

Returns metadata only — **keys are never returned**.

**Response**:
```json
[
  {
    "id": 1,
    "exchange_id": "bybit",
    "label": "Main Bybit Account",
    "is_testnet": false,
    "created_at": "2026-03-05T12:00:00Z"
  }
]
```

### Delete Credentials

```bash
curl -X DELETE -H "X-API-Key: $API_KEY" \
  http://localhost:8000/api/vault/credentials/1
```

Returns `204 No Content` on success.

### Test Credentials

Decrypts stored credentials and tests connectivity with the exchange via CCXT:

```bash
curl -X POST -H "X-API-Key: $API_KEY" \
  http://localhost:8000/api/vault/credentials/1/test
```

**Response (success)**:
```json
{
  "success": true,
  "message": "Successfully connected to bybit.",
  "exchange_info": {
    "exchange": "bybit",
    "testnet": false,
    "has_balance": true
  }
}
```

**Response (failure)**:
```json
{
  "success": false,
  "message": "Authentication failed. Check your API key and secret.",
  "exchange_info": null
}
```

The test endpoint uses `ccxt.fetch_balance()` — it only confirms connectivity, and does not return balance details.

---

## API Key Rotation

The API server supports key rotation with a 24-hour grace period (`src/api/routes/auth.py`):

### How It Works

1. A new API key is generated
2. The old key becomes the "grace key" — valid for 24 hours
3. During the grace period, both old and new keys are accepted
4. After 24 hours, only the new key works

### Rotation State

The rotation state is persisted to `data/api_key_rotation.json`:
```json
{
  "active_key": "<new-key>",
  "grace_key": "<old-key>",
  "grace_expires": "2026-03-06T12:00:00+00:00"
}
```

### Key Validation Order

1. Check against the active key (from rotation state or `API_KEY` env var)
2. If no match, check against the grace key (if still within the grace period)
3. Both checks use constant-time comparison (`hmac.compare_digest`)

---

## Security

### What Is Encrypted

| Data | Encrypted | Storage |
|------|-----------|---------|
| Exchange API key | Yes (Fernet) | PostgreSQL `credentials` table |
| Exchange API secret | Yes (Fernet) | PostgreSQL `credentials` table |
| Exchange passphrase | Yes (Fernet, if provided) | PostgreSQL `credentials` table |
| Exchange ID, label | No | PostgreSQL `credentials` table |
| Vault master key | No (must be provided) | `VAULT_MASTER_KEY` env var |
| API key | No | `API_KEY` env var or rotation state file |

### Encryption Details

- **Algorithm**: Fernet (AES-128-CBC + HMAC-SHA256)
- **Key**: 32-byte URL-safe base64-encoded (Fernet standard)
- **Ciphertext**: Base64-encoded, includes timestamp and HMAC
- **Tampering**: Any modification to the ciphertext causes decryption to fail with `InvalidToken`

### Threat Model

| Threat | Mitigation |
|--------|-----------|
| Database breach | Credentials encrypted at rest; master key is not in the database |
| Master key theft | Keep `VAULT_MASTER_KEY` in env vars, never in code or config files |
| API key exposure | 24-hour grace period enables rotation without downtime |
| Man-in-the-middle | Use HTTPS in production; API key header for authentication |
| Replay attacks | Fernet tokens include timestamps (not currently enforced for TTL) |

### Audit Logging

All credential operations (add, delete, test) are logged to the audit table:
- `credential_add` — when a new credential is stored
- `credential_delete` — when a credential is removed

Audit entries include the exchange ID, label, and testnet flag — never the actual keys.

---

## Master Key Rotation

Rotating the vault master key requires re-encrypting all stored credentials:

1. **Export current credentials** (while old key is active):
   - Use the `/test` endpoint to verify each credential works
   - Note which credential IDs exist

2. **Delete all credentials** via the API

3. **Update `VAULT_MASTER_KEY`** in `.env` with the new key

4. **Restart the API server**:
   ```bash
   docker compose up -d --no-deps api-server
   ```

5. **Re-store all credentials** with the same API key/secret values

There is no built-in migration tool — this is a manual process to ensure the old master key is fully retired.
