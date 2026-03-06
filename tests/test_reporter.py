"""Tests for src/services/reporter.py — ReporterService."""

import asyncio
import json
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub nats modules if not installed so the import doesn't fail at collection
if "nats" not in sys.modules:
    _nats = ModuleType("nats")
    _nats_aio = ModuleType("nats.aio")
    _nats_aio_msg = ModuleType("nats.aio.msg")
    _nats_aio_sub = ModuleType("nats.aio.subscription")
    _nats_aio_msg.Msg = MagicMock  # type: ignore[attr-defined]
    _nats_aio_sub.Subscription = MagicMock  # type: ignore[attr-defined]
    _nats.aio = _nats_aio  # type: ignore[attr-defined]
    _nats_aio.msg = _nats_aio_msg  # type: ignore[attr-defined]
    _nats_aio.subscription = _nats_aio_sub  # type: ignore[attr-defined]
    sys.modules["nats"] = _nats
    sys.modules["nats.aio"] = _nats_aio
    sys.modules["nats.aio.msg"] = _nats_aio_msg
    sys.modules["nats.aio.subscription"] = _nats_aio_sub

from src.services.reporter import ReporterService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_config():
    """Return a minimal mock config for ReporterService."""
    config = MagicMock()
    config.app_mode = "paper"
    config.messaging.servers = ["nats://localhost:4222"]
    config.messaging.subjects = {
        "performance": "perf.metrics",
        "reports": "reports.performance",
    }
    return config


@pytest.fixture
def reporter():
    return ReporterService()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReporterService:

    async def test_initial_state(self, reporter):
        """Freshly created service has no metrics or messaging."""
        assert reporter.config is None
        assert reporter.messaging is None
        assert reporter._latest_metrics is None

    @patch("src.services.reporter.MessagingClient")
    @patch("src.services.reporter.load_config")
    async def test_on_startup_connects_messaging(self, mock_load_config, MockMessaging, reporter):
        """Startup loads config, connects messaging, subscribes to performance subject."""
        mock_load_config.return_value = _mock_config()
        mock_client = AsyncMock()
        mock_sub = AsyncMock()
        mock_client.subscribe.return_value = mock_sub
        MockMessaging.return_value = mock_client

        await reporter.on_startup()

        mock_load_config.assert_called_once()
        mock_client.connect.assert_awaited_once()
        mock_client.subscribe.assert_awaited_once()
        # First arg of subscribe should be the performance subject
        assert mock_client.subscribe.call_args[0][0] == "perf.metrics"

        # Cleanup
        reporter._summary_task.cancel()
        try:
            await reporter._summary_task
        except asyncio.CancelledError:
            pass

    @patch("src.services.reporter.MessagingClient")
    @patch("src.services.reporter.load_config")
    async def test_on_shutdown_cleans_up(self, mock_load_config, MockMessaging, reporter):
        """Shutdown unsubscribes, cancels summary task, closes messaging."""
        mock_load_config.return_value = _mock_config()
        mock_client = AsyncMock()
        mock_sub = AsyncMock()
        mock_client.subscribe.return_value = mock_sub
        MockMessaging.return_value = mock_client

        await reporter.on_startup()
        await reporter.on_shutdown()

        mock_sub.unsubscribe.assert_awaited_once()
        mock_client.close.assert_awaited_once()
        assert reporter.messaging is None
        assert reporter._summary_task is None
        assert reporter._latest_metrics is None

    async def test_handle_metrics_stores_latest(self, reporter):
        """_handle_metrics parses JSON and stores latest metrics dict."""
        msg = MagicMock()
        msg.data = json.dumps({"equity": 50000, "pnl": 123.45}).encode("utf-8")

        await reporter._handle_metrics(msg)

        assert reporter._latest_metrics == {"equity": 50000, "pnl": 123.45}

    async def test_handle_metrics_bad_json(self, reporter):
        """Invalid JSON sets _latest_metrics to None."""
        msg = MagicMock()
        msg.data = b"not-json"

        await reporter._handle_metrics(msg)

        assert reporter._latest_metrics is None

    @patch("src.services.reporter.MessagingClient")
    @patch("src.services.reporter.load_config")
    async def test_publish_summary_publishes_metrics(self, mock_load_config, MockMessaging, reporter):
        """Summary loop publishes latest metrics with timestamp."""
        config = _mock_config()
        mock_load_config.return_value = config
        mock_client = AsyncMock()
        mock_client.subscribe.return_value = AsyncMock()
        MockMessaging.return_value = mock_client

        reporter.config = config
        reporter.messaging = mock_client
        reporter._latest_metrics = {"equity": 50000, "pnl": 100}

        # Run the loop briefly by patching sleep to raise after one iteration
        call_count = 0

        async def short_sleep(duration):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=short_sleep):
            with pytest.raises(asyncio.CancelledError):
                await reporter._publish_summary_loop()

        # Should have published once
        mock_client.publish.assert_awaited_once()
        published_subject = mock_client.publish.call_args[0][0]
        published_data = mock_client.publish.call_args[0][1]
        assert published_subject == "reports.performance"
        assert "timestamp" in published_data
        assert published_data["equity"] == 50000
