"""
Async LLM client for the agent orchestrator.

Calls the LLM proxy service's OpenAI-compatible endpoint.
Handles timeouts, retries, and connection errors.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when LLM communication fails."""


class LLMClient:
    """Async client for the LLM proxy service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 2,
    ):
        self.base_url = base_url or os.getenv("LLM_PROXY_URL", "http://localhost:8087")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a chat completion request to the LLM proxy.

        Returns the full response dict with 'choices' containing the LLM reply.
        Raises LLMError on failure after retries.
        """
        client = await self._ensure_client()
        payload: Dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if model:
            payload["model"] = model
        if response_format:
            payload["response_format"] = response_format

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "LLM request timeout (attempt %d/%d)",
                    attempt + 1,
                    self.max_retries + 1,
                )
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    logger.warning("LLM rate limited (attempt %d)", attempt + 1)
                else:
                    logger.error(
                        "LLM HTTP error %d: %s",
                        e.response.status_code,
                        e.response.text,
                    )
                    raise LLMError(f"LLM request failed: {e}") from e
            except httpx.ConnectError as e:
                last_error = e
                logger.warning(
                    "LLM proxy connection failed (attempt %d)", attempt + 1
                )

        raise LLMError(
            f"LLM request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
