"""Credential vault for secure storage of exchange API keys."""

import os

from cryptography.fernet import Fernet


def generate_master_key() -> str:
    """Generate a new Fernet-compatible master key (base64 encoded)."""
    return Fernet.generate_key().decode("utf-8")


def get_master_key() -> str:
    """Get master key from environment variable VAULT_MASTER_KEY.

    Raises:
        ValueError: If VAULT_MASTER_KEY is not set.
    """
    key = os.environ.get("VAULT_MASTER_KEY")
    if not key:
        raise ValueError(
            "VAULT_MASTER_KEY environment variable is not set. "
            "Generate one with: python -c "
            "\"from src.security.credential_vault import generate_master_key; print(generate_master_key())\""
        )
    return key


def encrypt_credential(plaintext: str, master_key: str) -> str:
    """Encrypt a credential string using Fernet (AES-128-CBC with HMAC).

    Args:
        plaintext: The credential value to encrypt.
        master_key: Fernet-compatible base64-encoded key.

    Returns:
        Base64-encoded ciphertext string.
    """
    f = Fernet(master_key.encode("utf-8") if isinstance(master_key, str) else master_key)
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_credential(ciphertext: str, master_key: str) -> str:
    """Decrypt a credential string using Fernet.

    Args:
        ciphertext: Base64-encoded ciphertext from encrypt_credential.
        master_key: Fernet-compatible base64-encoded key.

    Returns:
        Decrypted plaintext string.

    Raises:
        cryptography.fernet.InvalidToken: If the key is wrong or data is tampered.
    """
    f = Fernet(master_key.encode("utf-8") if isinstance(master_key, str) else master_key)
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
