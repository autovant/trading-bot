"""
LLM Proxy Service — OpenAI-compatible chat completions endpoint.

Acts as a proxy between the agent orchestrator and LLM providers.
Primary provider: configurable OpenAI-compatible API.
Fallback provider: Google Gemini via google-generativeai SDK.

Run with: uvicorn src.services.llm_proxy:app --port 8087
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.logging_config import CorrelationIdMiddleware, setup_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai-compatible")
LLM_PROVIDER_URL = os.getenv(
    "LLM_PROVIDER_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai",
)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")
LLM_RATE_LIMIT_RPM = int(os.getenv("LLM_RATE_LIMIT_RPM", "30"))
LLM_CACHE_TTL_SECONDS = int(os.getenv("LLM_CACHE_TTL_SECONDS", "300"))


# ---------------------------------------------------------------------------
# Pydantic models (OpenAI-compatible)
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str


class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: Optional[float] = 0.3
    max_tokens: Optional[int] = 2048
    response_format: Optional[Dict[str, Any]] = None


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int = 0
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage = ChatCompletionUsage()


# ---------------------------------------------------------------------------
# Rate limiter — token bucket
# ---------------------------------------------------------------------------
class TokenBucketRateLimiter:
    """Per-service token bucket rate limiter."""

    def __init__(self, rate: int = 30, per: float = 60.0):
        self.rate = rate
        self.per = per
        self.tokens = float(rate)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.per))
            self.last_refill = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------
class ResponseCache:
    """In-memory response cache keyed on SHA-256 of messages + model."""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 1000):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._cache: Dict[str, tuple[dict, float]] = {}

    def _key(self, messages: List[ChatMessage], model: str) -> str:
        raw = json.dumps(
            [{"role": m.role, "content": m.content} for m in messages] + [model],
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, messages: List[ChatMessage], model: str) -> Optional[dict]:
        key = self._key(messages, model)
        entry = self._cache.get(key)
        if entry is not None:
            resp, ts = entry
            if time.monotonic() - ts < self.ttl:
                return resp
            del self._cache[key]
        return None

    def put(self, messages: List[ChatMessage], model: str, response: dict) -> None:
        key = self._key(messages, model)
        self._cache[key] = (response, time.monotonic())
        self._evict()

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts >= self.ttl]
        for k in expired:
            del self._cache[k]
        # Evict oldest entries if over capacity
        if len(self._cache) > self.max_entries:
            by_age = sorted(self._cache.items(), key=lambda kv: kv[1][1])
            for k, _ in by_age[: len(self._cache) - self.max_entries]:
                del self._cache[k]


# ---------------------------------------------------------------------------
# LLM provider calls
# ---------------------------------------------------------------------------
def _get_llm_api_key() -> str:
    """Read LLM API key from environment at call time (supports rotation)."""
    key = os.getenv("LLM_API_KEY", "")
    if not key:
        raise ValueError("LLM_API_KEY not configured")
    return key


def _get_gemini_api_key() -> str:
    """Read Gemini API key from environment at call time."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("GEMINI_API_KEY not configured")
    return key


async def _call_primary(
    client: httpx.AsyncClient,
    request: ChatCompletionRequest,
    model: str,
) -> dict:
    """Call the primary OpenAI-compatible provider."""
    api_key = _get_llm_api_key()

    url = f"{LLM_PROVIDER_URL.rstrip('/')}/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    if request.response_format:
        payload["response_format"] = request.response_format

    resp = await client.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    resp.raise_for_status()
    return resp.json()


async def _call_gemini_fallback(
    request: ChatCompletionRequest,
    model: str,
) -> dict:
    """Fallback: call Google Gemini via the google-generativeai SDK."""
    gemini_key = _get_gemini_api_key()

    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise RuntimeError("google-generativeai package not installed") from exc

    genai.configure(api_key=gemini_key)

    # Convert messages to Gemini format
    system_instruction: Optional[str] = None
    contents: List[Dict[str, Any]] = []
    for msg in request.messages:
        if msg.role == "system":
            system_instruction = msg.content
        else:
            gemini_role = "model" if msg.role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": msg.content}]})

    gemini_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_instruction,
    )

    generation_config: Dict[str, Any] = {}
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature
    if request.max_tokens is not None:
        generation_config["max_output_tokens"] = request.max_tokens

    gemini_response = await gemini_model.generate_content_async(
        contents,
        generation_config=generation_config if generation_config else None,
    )

    # Convert Gemini response to OpenAI format
    response_text = gemini_response.text if gemini_response.text else ""
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(role="assistant", content=response_text),
            )
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# GitHub Copilot provider
# ---------------------------------------------------------------------------
_copilot_session_token: Optional[str] = None
_copilot_token_expires: float = 0.0


async def _get_copilot_session_token(client: httpx.AsyncClient) -> str:
    """Get or refresh the Copilot session token from GitHub."""
    global _copilot_session_token, _copilot_token_expires

    # Reuse unexpired token (with 60s buffer)
    if _copilot_session_token and time.time() < _copilot_token_expires - 60:
        return _copilot_session_token

    github_token = os.getenv("COPILOT_GITHUB_TOKEN", "")
    if not github_token:
        # Try reading from file
        token_file = "/app/.copilot_token"
        if os.path.exists(token_file):
            with open(token_file) as f:
                github_token = f.read().strip()
    if not github_token:
        raise ValueError("COPILOT_GITHUB_TOKEN not configured")

    resp = await client.get(
        "https://api.github.com/copilot_internal/v2/token",
        headers={
            "Authorization": f"token {github_token}",
            "Accept": "application/json",
            "User-Agent": "trading-bot/1.0",
        },
    )
    resp.raise_for_status()
    data = resp.json()

    _copilot_session_token = data["token"]
    _copilot_token_expires = data.get("expires_at", time.time() + 1800)
    if isinstance(_copilot_token_expires, str):
        from datetime import datetime
        _copilot_token_expires = datetime.fromisoformat(
            _copilot_token_expires.replace("Z", "+00:00")
        ).timestamp()

    logger.info("Copilot session token refreshed, expires in %.0fs",
                _copilot_token_expires - time.time())
    return _copilot_session_token


async def _call_copilot(
    client: httpx.AsyncClient,
    request: ChatCompletionRequest,
    model: str,
) -> dict:
    """Call GitHub Copilot's OpenAI-compatible API."""
    session_token = await _get_copilot_session_token(client)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
    }
    if request.response_format:
        payload["response_format"] = request.response_format

    resp = await client.post(
        "https://api.githubcopilot.com/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {session_token}",
            "Content-Type": "application/json",
            "Editor-Version": "vscode/1.96.0",
            "Copilot-Integration-Id": "vscode-chat",
        },
    )

    if resp.status_code == 401:
        # Token expired, force refresh
        global _copilot_session_token
        _copilot_session_token = None
        session_token = await _get_copilot_session_token(client)
        resp = await client.post(
            "https://api.githubcopilot.com/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {session_token}",
                "Content-Type": "application/json",
                "Editor-Version": "vscode/1.96.0",
                "Copilot-Integration-Id": "vscode-chat",
            },
        )

    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
rate_limiter = TokenBucketRateLimiter(rate=LLM_RATE_LIMIT_RPM)
cache = ResponseCache(ttl_seconds=LLM_CACHE_TTL_SECONDS)
_http_client: Optional[httpx.AsyncClient] = None


async def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=60.0)
    return _http_client


app = FastAPI(title="LLM Proxy Service", version="1.0.0")
app.add_middleware(CorrelationIdMiddleware)
setup_logging("llm-proxy")


@app.on_event("startup")
async def _startup() -> None:
    logger.info(
        "LLM Proxy starting — provider=%s fallback_url=%s model=%s rate_limit=%d/min cache_ttl=%ds",
        LLM_PROVIDER,
        LLM_PROVIDER_URL,
        LLM_MODEL,
        LLM_RATE_LIMIT_RPM,
        LLM_CACHE_TTL_SECONDS,
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
    logger.info("LLM Proxy shut down")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "llm-proxy"})


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest, raw: Request) -> ChatCompletionResponse:
    # Rate limiting
    if not await rate_limiter.acquire():
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    model = request.model or LLM_MODEL

    # Check cache
    cached = cache.get(request.messages, model)
    if cached is not None:
        logger.debug("Cache hit for model=%s", model)
        return ChatCompletionResponse(**cached)

    client = await _get_http_client()

    # Route to the configured provider
    if LLM_PROVIDER == "github-copilot":
        try:
            copilot_model = model if model != LLM_MODEL else "gpt-4o"
            result = await _call_copilot(client, request, copilot_model)
            logger.info("Copilot provider succeeded model=%s", copilot_model)
            cache.put(request.messages, model, result)
            return ChatCompletionResponse(**result)
        except Exception as copilot_err:
            logger.warning("Copilot provider failed: %s — trying fallback", copilot_err)

    # Try primary provider (OpenAI-compatible)
    if LLM_PROVIDER != "github-copilot":
        try:
            result = await _call_primary(client, request, model)
            logger.info("Primary provider succeeded model=%s", model)
            cache.put(request.messages, model, result)
            return ChatCompletionResponse(**result)
        except Exception as primary_err:
            logger.warning("Primary provider failed: %s — trying Gemini fallback", primary_err)

    # Try Gemini fallback
    try:
        result = await _call_gemini_fallback(request, model)
        logger.info("Gemini fallback succeeded model=%s", model)
        cache.put(request.messages, model, result)
        return ChatCompletionResponse(**result)
    except Exception as fallback_err:
        logger.error("All LLM providers failed: %s", fallback_err)
        raise HTTPException(
            status_code=503,
            detail="All LLM providers unavailable",
        ) from fallback_err
