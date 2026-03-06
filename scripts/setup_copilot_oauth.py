#!/usr/bin/env python3
"""
GitHub Copilot OAuth Device Flow Setup.

Authenticates with GitHub using the device code flow and saves
the OAuth token for use by the LLM proxy service.

Usage:
    python scripts/setup_copilot_oauth.py

The token is saved to .copilot_token (gitignored) and can be
loaded via the COPILOT_GITHUB_TOKEN environment variable.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

# VS Code Copilot Chat client ID (public, used for device flow)
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
TOKEN_FILE = Path(__file__).parent.parent / ".copilot_token"


def device_flow() -> str:
    """Run the GitHub device code OAuth flow and return the access token."""
    with httpx.Client(timeout=30.0) as client:
        # Step 1: Request device code
        resp = client.post(
            "https://github.com/login/device/code",
            data={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

        device_code = data["device_code"]
        user_code = data["user_code"]
        verification_uri = data["verification_uri"]
        interval = data.get("interval", 5)

        print(f"\n{'='*50}")
        print(f"  Open: {verification_uri}")
        print(f"  Enter code: {user_code}")
        print(f"{'='*50}\n")
        print("Waiting for authorization...", flush=True)

        # Step 2: Poll for token
        while True:
            time.sleep(interval)
            token_resp = client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": COPILOT_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

            error = token_data.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval = token_data.get("interval", interval + 5)
                continue
            elif error:
                print(f"Error: {error} — {token_data.get('error_description', '')}")
                sys.exit(1)

            access_token = token_data.get("access_token")
            if access_token:
                return access_token


def verify_copilot_access(github_token: str) -> bool:
    """Verify the token can obtain a Copilot session token."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            "https://api.github.com/copilot_internal/v2/token",
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/json",
                "User-Agent": "trading-bot/1.0",
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"Copilot access verified. Token expires: {data.get('expires_at', 'unknown')}")
            return True
        else:
            print(f"Copilot access check failed: {resp.status_code} {resp.text}")
            return False


def main() -> None:
    print("GitHub Copilot OAuth Setup")
    print("-" * 30)

    # Check if token already exists
    existing = os.getenv("COPILOT_GITHUB_TOKEN") or ""
    if not existing and TOKEN_FILE.exists():
        existing = TOKEN_FILE.read_text().strip()

    if existing:
        print("Found existing token, verifying...")
        if verify_copilot_access(existing):
            print("Existing token is valid. No action needed.")
            return
        print("Existing token is invalid. Starting new auth flow...\n")

    token = device_flow()
    print("\nAuthentication successful!")

    # Verify Copilot access
    if not verify_copilot_access(token):
        print("\nWARNING: Token works for GitHub but Copilot access not confirmed.")
        print("Ensure you have an active GitHub Copilot subscription.")

    # Save token
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    print(f"\nToken saved to {TOKEN_FILE}")
    print(f"\nTo use in Docker, add to .env:")
    print(f"  COPILOT_GITHUB_TOKEN={token}")

    # Also update .env if it exists
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        env_content = env_file.read_text()
        if "COPILOT_GITHUB_TOKEN=" in env_content:
            lines = env_content.splitlines()
            updated = []
            for line in lines:
                if line.startswith("COPILOT_GITHUB_TOKEN="):
                    updated.append(f"COPILOT_GITHUB_TOKEN={token}")
                else:
                    updated.append(line)
            env_file.write_text("\n".join(updated) + "\n")
        else:
            with open(env_file, "a") as f:
                f.write(f"\nCOPILOT_GITHUB_TOKEN={token}\n")
        print("Updated .env file with token.")


if __name__ == "__main__":
    main()
