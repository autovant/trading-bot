"""Vault API routes for managing encrypted exchange credentials."""

import logging
from typing import List, Optional

import ccxt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator

from src.database import DatabaseManager
from src.security.credential_vault import (
    decrypt_credential,
    encrypt_credential,
    get_master_key,
)

logger = logging.getLogger(__name__)

vault_router = APIRouter(tags=["vault"])

# Supported exchanges (must match ccxt exchange ids)
SUPPORTED_EXCHANGES = {
    "bybit",
    "binance",
    "okx",
    "coinbase",
    "kraken",
    "bitget",
    "kucoin",
    "gate",
    "htx",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CredentialCreateRequest(BaseModel):
    exchange_id: str
    label: str
    api_key: str
    api_secret: str
    passphrase: Optional[str] = None
    is_testnet: bool = False

    @field_validator("exchange_id")
    @classmethod
    def validate_exchange_id(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in SUPPORTED_EXCHANGES:
            raise ValueError(
                f"Unsupported exchange: {v}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXCHANGES))}"
            )
        return v


class CredentialResponse(BaseModel):
    id: int
    exchange_id: str
    label: str
    is_testnet: bool
    created_at: str


class CredentialTestResponse(BaseModel):
    success: bool
    message: str
    exchange_info: Optional[dict] = None


# ---------------------------------------------------------------------------
# Dependencies — overridden at app startup (same pattern as other routes)
# ---------------------------------------------------------------------------

async def get_db() -> DatabaseManager:
    raise NotImplementedError


def get_exchange():
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _require_master_key() -> str:
    """Return the vault master key or raise 503."""
    try:
        return get_master_key()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault master key is not configured.",
        ) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@vault_router.post(
    "/api/vault/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential(
    request: CredentialCreateRequest,
    db: DatabaseManager = Depends(get_db),
):
    """Store a new set of exchange API credentials (encrypted)."""
    master_key = _require_master_key()

    encrypted_key = encrypt_credential(request.api_key, master_key)
    encrypted_secret = encrypt_credential(request.api_secret, master_key)
    encrypted_passphrase = (
        encrypt_credential(request.passphrase, master_key)
        if request.passphrase
        else None
    )

    credential_id = await db.store_credential(
        exchange_id=request.exchange_id,
        label=request.label,
        api_key_enc=encrypted_key,
        api_secret_enc=encrypted_secret,
        passphrase_enc=encrypted_passphrase,
        is_testnet=request.is_testnet,
    )

    if credential_id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store credential.",
        )

    credential = await db.get_credential(credential_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Credential stored but could not be retrieved.",
        )

    # Audit log (fire-and-forget)
    try:
        await db.log_audit(
            action="credential_add",
            resource_type="credential",
            resource_id=str(credential_id),
            details={"exchange_id": request.exchange_id, "label": request.label, "is_testnet": request.is_testnet},
            actor="api",
        )
    except Exception:
        logger.warning("Failed to log audit for credential_add id=%s", credential_id, exc_info=True)

    return CredentialResponse(
        id=credential["id"],
        exchange_id=credential["exchange_id"],
        label=credential["label"],
        is_testnet=credential["is_testnet"],
        created_at=credential["created_at"],
    )


@vault_router.get(
    "/api/vault/credentials",
    response_model=List[CredentialResponse],
)
async def list_credentials(
    db: DatabaseManager = Depends(get_db),
):
    """List all stored credentials (metadata only — keys are never returned)."""
    rows = await db.list_credentials()
    return [
        CredentialResponse(
            id=row["id"],
            exchange_id=row["exchange_id"],
            label=row["label"],
            is_testnet=row["is_testnet"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@vault_router.delete(
    "/api/vault/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_credential(
    credential_id: int,
    db: DatabaseManager = Depends(get_db),
):
    """Delete a credential by ID."""
    existing = await db.get_credential(credential_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found.",
        )
    await db.delete_credential(credential_id)

    # Audit log (fire-and-forget)
    try:
        await db.log_audit(
            action="credential_delete",
            resource_type="credential",
            resource_id=str(credential_id),
            details={"exchange_id": existing["exchange_id"], "label": existing["label"]},
            actor="api",
        )
    except Exception:
        logger.warning("Failed to log audit for credential_delete id=%s", credential_id, exc_info=True)


@vault_router.post(
    "/api/vault/credentials/{credential_id}/test",
    response_model=CredentialTestResponse,
)
async def test_credential(
    credential_id: int,
    db: DatabaseManager = Depends(get_db),
):
    """Decrypt credentials and test exchange connectivity via CCXT."""
    master_key = _require_master_key()

    credential = await db.get_credential(credential_id)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found.",
        )

    exchange_id = credential["exchange_id"]

    # Resolve ccxt exchange class
    exchange_cls = getattr(ccxt, exchange_id, None)
    if exchange_cls is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Exchange '{exchange_id}' is not available in CCXT.",
        )

    try:
        api_key = decrypt_credential(credential["api_key_enc"], master_key)
        api_secret = decrypt_credential(credential["api_secret_enc"], master_key)
        passphrase = (
            decrypt_credential(credential["passphrase_enc"], master_key)
            if credential.get("passphrase_enc")
            else None
        )
    except Exception:
        logger.exception("Failed to decrypt credentials for id=%s", credential_id)
        return CredentialTestResponse(
            success=False,
            message="Failed to decrypt stored credentials. Master key may have changed.",
        )

    # Build exchange config
    config = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
    }
    if passphrase:
        config["password"] = passphrase
    if credential.get("is_testnet"):
        config["sandbox"] = True

    try:
        exchange = exchange_cls(config)
        exchange_info = await exchange.fetch_balance()

        # Redact all but confirmation of connectivity
        return CredentialTestResponse(
            success=True,
            message=f"Successfully connected to {exchange_id}.",
            exchange_info={
                "exchange": exchange_id,
                "testnet": credential.get("is_testnet", False),
                "has_balance": bool(exchange_info),
            },
        )
    except ccxt.AuthenticationError:
        return CredentialTestResponse(
            success=False,
            message="Authentication failed. Check your API key and secret.",
        )
    except ccxt.NetworkError as exc:
        return CredentialTestResponse(
            success=False,
            message=f"Network error connecting to {exchange_id}: {exc}",
        )
    except Exception:
        logger.exception("Exchange test failed for id=%s", credential_id)
        return CredentialTestResponse(
            success=False,
            message="Connection test failed. Check credentials and try again.",
        )
    finally:
        try:
            await exchange.close()
        except Exception:
            logger.debug("Failed to close exchange client during credential test", exc_info=True)


# ---------------------------------------------------------------------------
# Key Rotation
# ---------------------------------------------------------------------------


class KeyRotationRequest(BaseModel):
    credential_id: int
    new_api_key: str
    new_api_secret: str
    new_passphrase: Optional[str] = None


class KeyRotationResponse(BaseModel):
    success: bool
    message: str
    credential_id: int


@vault_router.post(
    "/api/vault/credentials/{credential_id}/rotate",
    response_model=KeyRotationResponse,
)
async def rotate_api_key(
    credential_id: int,
    request: KeyRotationRequest,
    db: DatabaseManager = Depends(get_db),
):
    """Rotate API keys for an existing credential.

    Encrypts the new keys with the current master key and updates the
    stored credential. The old keys are overwritten and cannot be recovered.
    """
    master_key = _require_master_key()

    existing = await db.get_credential(credential_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found.",
        )

    # Encrypt new credentials
    encrypted_key = encrypt_credential(request.new_api_key, master_key)
    encrypted_secret = encrypt_credential(request.new_api_secret, master_key)
    encrypted_passphrase = (
        encrypt_credential(request.new_passphrase, master_key)
        if request.new_passphrase
        else existing.get("passphrase_enc")
    )

    # Update in database
    await db.update_credential(
        credential_id=credential_id,
        api_key_enc=encrypted_key,
        api_secret_enc=encrypted_secret,
        passphrase_enc=encrypted_passphrase,
    )

    # Audit log
    try:
        await db.log_audit(
            action="credential_rotate",
            resource_type="credential",
            resource_id=str(credential_id),
            details={
                "exchange_id": existing["exchange_id"],
                "label": existing["label"],
            },
            actor="api",
        )
    except Exception:
        logger.warning("Failed to log audit for credential_rotate id=%s", credential_id, exc_info=True)

    logger.info(
        "API key rotated for credential id=%s exchange=%s",
        credential_id,
        existing["exchange_id"],
    )

    return KeyRotationResponse(
        success=True,
        message=f"API keys rotated successfully for {existing['exchange_id']} ({existing['label']}).",
        credential_id=credential_id,
    )
