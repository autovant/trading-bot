"""Tests for src/services/llm_proxy.py — LLM Proxy Service."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from src.services.llm_proxy import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ResponseCache,
    TokenBucketRateLimiter,
    app,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rate_limiter():
    return TokenBucketRateLimiter(rate=5, per=1.0)


@pytest.fixture
def cache():
    return ResponseCache(ttl_seconds=10, max_entries=100)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_request(content: str = "Hello") -> ChatCompletionRequest:
    return ChatCompletionRequest(
        messages=[ChatMessage(role="user", content=content)],
        model="test-model",
    )


def _make_response_dict(content: str = "Hi there") -> dict:
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    async def test_health_returns_200(self, client):
        """GET /health returns 200 with service name."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "llm-proxy"


# ---------------------------------------------------------------------------
# Rate limiter unit tests
# ---------------------------------------------------------------------------

class TestTokenBucketRateLimiter:

    async def test_acquire_within_limit(self, rate_limiter):
        """Requests within rate limit succeed."""
        for _ in range(5):
            assert await rate_limiter.acquire() is True

    async def test_acquire_exceeds_limit(self, rate_limiter):
        """Requests exceeding rate limit are rejected."""
        for _ in range(5):
            await rate_limiter.acquire()
        assert await rate_limiter.acquire() is False

    async def test_tokens_refill_over_time(self):
        """Tokens refill after waiting."""
        rl = TokenBucketRateLimiter(rate=2, per=0.1)
        assert await rl.acquire() is True
        assert await rl.acquire() is True
        assert await rl.acquire() is False  # exhausted

        await asyncio.sleep(0.15)  # wait for refill
        assert await rl.acquire() is True


# ---------------------------------------------------------------------------
# Response cache unit tests
# ---------------------------------------------------------------------------

class TestResponseCache:

    def test_cache_miss(self, cache):
        """Unknown request returns None."""
        msgs = [ChatMessage(role="user", content="test")]
        assert cache.get(msgs, "model") is None

    def test_cache_put_and_get(self, cache):
        """Cached response is returned on matching request."""
        msgs = [ChatMessage(role="user", content="hello")]
        resp = _make_response_dict()
        cache.put(msgs, "model-a", resp)
        cached = cache.get(msgs, "model-a")
        assert cached == resp

    def test_cache_different_model_misses(self, cache):
        """Different model name doesn't match cached entry."""
        msgs = [ChatMessage(role="user", content="hello")]
        cache.put(msgs, "model-a", _make_response_dict())
        assert cache.get(msgs, "model-b") is None

    def test_cache_ttl_expiry(self):
        """Expired entries return None."""
        c = ResponseCache(ttl_seconds=0, max_entries=100)
        msgs = [ChatMessage(role="user", content="hi")]
        c.put(msgs, "m", _make_response_dict())
        # ttl=0 means immediate expiry
        assert c.get(msgs, "m") is None

    def test_cache_eviction_on_max_entries(self):
        """Oldest entries are evicted when max_entries is exceeded."""
        c = ResponseCache(ttl_seconds=300, max_entries=2)
        for i in range(3):
            msgs = [ChatMessage(role="user", content=f"msg-{i}")]
            c.put(msgs, "m", _make_response_dict(f"resp-{i}"))
        # Oldest entry (msg-0) should be evicted
        assert len(c._cache) <= 2


# ---------------------------------------------------------------------------
# Chat completion endpoint
# ---------------------------------------------------------------------------

class TestChatCompletions:

    @patch("src.services.llm_proxy.rate_limiter")
    @patch("src.services.llm_proxy.cache")
    @patch("src.services.llm_proxy._get_http_client")
    @patch("src.services.llm_proxy._call_primary")
    async def test_primary_provider_success(
        self, mock_call_primary, mock_get_client, mock_cache, mock_rl, client
    ):
        """Successful primary provider call returns well-formed response."""
        mock_rl.acquire = AsyncMock(return_value=True)
        mock_cache.get.return_value = None
        mock_cache.put = MagicMock()
        mock_get_client.return_value = AsyncMock()
        mock_call_primary.return_value = _make_response_dict("world")

        resp = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "world"

    @patch("src.services.llm_proxy.rate_limiter")
    async def test_rate_limit_returns_429(self, mock_rl, client):
        """Rate-limited request returns HTTP 429."""
        mock_rl.acquire = AsyncMock(return_value=False)

        resp = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 429

    @patch("src.services.llm_proxy.rate_limiter")
    @patch("src.services.llm_proxy.cache")
    async def test_cache_hit_returns_cached(self, mock_cache, mock_rl, client):
        """Cached response is returned without calling provider."""
        mock_rl.acquire = AsyncMock(return_value=True)
        cached_resp = _make_response_dict("cached")
        mock_cache.get.return_value = cached_resp

        resp = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "cached"

    @patch("src.services.llm_proxy.rate_limiter")
    @patch("src.services.llm_proxy.cache")
    @patch("src.services.llm_proxy._get_http_client")
    @patch("src.services.llm_proxy._call_primary")
    @patch("src.services.llm_proxy._call_gemini_fallback")
    async def test_provider_fallback(
        self, mock_gemini, mock_primary, mock_get_client, mock_cache, mock_rl, client
    ):
        """Primary failure falls back to Gemini."""
        mock_rl.acquire = AsyncMock(return_value=True)
        mock_cache.get.return_value = None
        mock_cache.put = MagicMock()
        mock_get_client.return_value = AsyncMock()
        mock_primary.side_effect = Exception("primary down")
        mock_gemini.return_value = _make_response_dict("from gemini")

        resp = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "from gemini"
        mock_gemini.assert_awaited_once()

    @patch("src.services.llm_proxy.rate_limiter")
    @patch("src.services.llm_proxy.cache")
    @patch("src.services.llm_proxy._get_http_client")
    @patch("src.services.llm_proxy._call_primary")
    @patch("src.services.llm_proxy._call_gemini_fallback")
    async def test_all_providers_fail_returns_503(
        self, mock_gemini, mock_primary, mock_get_client, mock_cache, mock_rl, client
    ):
        """All providers failing returns 503."""
        mock_rl.acquire = AsyncMock(return_value=True)
        mock_cache.get.return_value = None
        mock_get_client.return_value = AsyncMock()
        mock_primary.side_effect = Exception("primary down")
        mock_gemini.side_effect = Exception("gemini down")

        resp = await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
        assert resp.status_code == 503

    async def test_invalid_request_body_returns_422(self, client):
        """Missing 'messages' field returns 422."""
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "test"},
        )
        assert resp.status_code == 422
