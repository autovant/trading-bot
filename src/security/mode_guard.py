from __future__ import annotations

import os
from typing import Dict, Optional, Tuple


def _is_testnet_url(url: Optional[str]) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return "testnet" in lowered or "sandbox" in lowered


def resolve_exchange_credentials(*, testnet: bool) -> Dict[str, Optional[str]]:
    prefix = "EXCHANGE_TESTNET" if testnet else "EXCHANGE"
    return {
        "api_key": os.getenv(f"{prefix}_API_KEY"),
        "secret_key": os.getenv(f"{prefix}_SECRET_KEY"),
        "passphrase": os.getenv(f"{prefix}_PASSPHRASE"),
    }


def resolve_zoomex_credentials(*, use_testnet: bool) -> Tuple[Optional[str], Optional[str]]:
    prefix = "ZOOMEX_TESTNET" if use_testnet else "ZOOMEX"
    return (
        os.getenv(f"{prefix}_API_KEY"),
        os.getenv(f"{prefix}_API_SECRET"),
    )


def require_credentials(label: str, api_key: Optional[str], api_secret: Optional[str]) -> None:
    if not api_key or not api_secret:
        raise ValueError(f"{label} API credentials are required but not set")


def validate_mode_config(
    *,
    mode_name: str,
    exchange_testnet: bool,
    perps_testnet: bool,
    exchange_base_url: Optional[str],
) -> None:
    normalized = mode_name.lower()
    if normalized == "live":
        if exchange_testnet:
            raise ValueError("Live mode cannot use testnet exchange endpoints.")
        if perps_testnet:
            raise ValueError("Live mode cannot use testnet perps endpoints.")
        if _is_testnet_url(exchange_base_url):
            raise ValueError("Live mode cannot use a testnet exchange base URL.")
    elif normalized == "testnet":
        if not exchange_testnet:
            raise ValueError("Testnet mode requires exchange.testnet=true.")
        if not perps_testnet:
            raise ValueError("Testnet mode requires perps.useTestnet=true.")
        if not exchange_base_url or not _is_testnet_url(exchange_base_url):
            raise ValueError("Testnet mode requires a testnet exchange base URL.")
