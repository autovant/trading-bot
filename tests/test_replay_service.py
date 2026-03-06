"""Tests for src/services/replay.py — ReplayService."""

import sys
from datetime import datetime, timezone
from pathlib import Path
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

from src.services.replay import ReplayService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_config(speed: str = "1x", source: str = "sample_data/"):
    """Return a minimal mock config for ReplayService."""
    config = MagicMock()
    config.app_mode = "replay"
    config.messaging.servers = ["nats://localhost:4222"]
    config.messaging.subjects = {
        "market_data": "market.tick",
        "replay_control": "replay.control",
    }
    config.replay.speed = speed
    config.replay.source = source
    config.trading.symbols = ["BTCUSDT"]
    return config


@pytest.fixture
def service():
    return ReplayService()


# ---------------------------------------------------------------------------
# Unit tests — static/helper methods
# ---------------------------------------------------------------------------

class TestReplayBuildSnapshot:
    """Test ReplayService._build_snapshot() static method."""

    def test_build_snapshot_structure(self):
        """Snapshot has expected keys (symbol, best_bid, best_ask, etc.)."""
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        snap = ReplayService._build_snapshot("BTCUSDT", ts, 40000, 41000, 39000, 40500, 100)

        assert snap["symbol"] == "BTCUSDT"
        assert snap["close"] == 40500
        assert snap["open"] == 40000
        assert snap["high"] == 41000
        assert snap["low"] == 39000
        assert snap["volume"] == 100
        assert snap["last_price"] == 40500
        assert "best_bid" in snap
        assert "best_ask" in snap
        assert snap["best_bid"] < snap["best_ask"]
        assert snap["timestamp"] == ts.isoformat()
        assert "order_flow_imbalance" in snap

    def test_build_snapshot_buy_side(self):
        """Close >= open → last_side is 'buy'."""
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        snap = ReplayService._build_snapshot("ETH", ts, 100, 110, 90, 105, 50)
        assert snap["last_side"] == "buy"

    def test_build_snapshot_sell_side(self):
        """Close < open → last_side is 'sell'."""
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        snap = ReplayService._build_snapshot("ETH", ts, 100, 110, 90, 95, 50)
        assert snap["last_side"] == "sell"


class TestReplayParseSource:
    """Test ReplayService._parse_source()."""

    def test_parse_source_with_scheme(self):
        scheme, path = ReplayService._parse_source("parquet://data/ohlcv")
        assert scheme == "parquet"
        assert isinstance(path, Path)

    def test_parse_source_without_scheme(self):
        scheme, path = ReplayService._parse_source("data/ohlcv.csv")
        assert scheme == ""
        assert isinstance(path, Path)


class TestReplayCoerceTimestamp:
    """Test ReplayService._coerce_timestamp()."""

    def test_datetime_passthrough(self):
        dt = datetime(2024, 6, 15, tzinfo=timezone.utc)
        assert ReplayService._coerce_timestamp(dt) == dt

    def test_epoch_seconds(self):
        result = ReplayService._coerce_timestamp(1700000000)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_iso_string(self):
        result = ReplayService._coerce_timestamp("2024-01-01T00:00:00+00:00")
        assert isinstance(result, datetime)


class TestReplayDeriveInterval:
    """Test ReplayService._derive_interval()."""

    def test_1x_speed(self, service):
        service.config = _mock_config(speed="1x")
        assert service._derive_interval() == 1.0

    def test_10x_speed(self, service):
        service.config = _mock_config(speed="10x")
        assert service._derive_interval() == 0.1

    def test_100x_speed_clamped(self, service):
        service.config = _mock_config(speed="100x")
        assert service._derive_interval() == 0.05  # minimum


# ---------------------------------------------------------------------------
# Service lifecycle tests
# ---------------------------------------------------------------------------

class TestReplaySetState:
    """Test ReplayService.set_state()."""

    async def test_pause_clears_running(self, service):
        service._running.set()
        await service.set_state("pause")
        assert service.state == "paused"
        assert service._last_control == "pause"
        assert service._last_control_at is not None

    async def test_resume_sets_running(self, service):
        service._running.clear()
        await service.set_state("resume")
        assert service.state == "running"
        assert service._last_control == "resume"

    async def test_invalid_action_raises(self, service):
        with pytest.raises(ValueError, match="Unsupported"):
            await service.set_state("rewind")


class TestReplayStatusPayload:
    """Test ReplayService.status_payload()."""

    def test_status_payload_default(self, service):
        payload = service.status_payload()
        assert payload["state"] == "paused"  # _running not set
        assert payload["dataset_size"] == 0
        assert payload["last_control"] is None

    async def test_status_payload_after_control(self, service):
        await service.set_state("pause")
        payload = service.status_payload()
        assert payload["state"] == "paused"
        assert payload["last_control"] == "pause"
        assert payload["last_control_at"] is not None


class TestReplayOnStartupEmpty:
    """Test ReplayService.on_startup with empty dataset."""

    @patch("src.services.replay.MessagingClient")
    @patch("src.services.replay.load_config")
    async def test_startup_empty_dataset_idles(self, mock_load_config, MockMessaging, service):
        """Service with empty dataset starts but idles (no loop task)."""
        mock_load_config.return_value = _mock_config()
        mock_client = AsyncMock()
        mock_client.subscribe.return_value = AsyncMock()
        MockMessaging.return_value = mock_client

        with patch.object(service, "_load_dataset", return_value=[]):
            await service.on_startup()

        assert service._dataset == []
        assert service._loop_task is None  # no loop started
        mock_client.subscribe.assert_awaited_once()  # control sub registered

        await service.on_shutdown()

    @patch("src.services.replay.MessagingClient")
    @patch("src.services.replay.load_config")
    async def test_shutdown_cleans_up(self, mock_load_config, MockMessaging, service):
        """Shutdown unsubscribes control, cancels loop, closes messaging."""
        mock_load_config.return_value = _mock_config()
        mock_client = AsyncMock()
        mock_sub = AsyncMock()
        mock_client.subscribe.return_value = mock_sub
        MockMessaging.return_value = mock_client

        with patch.object(service, "_load_dataset", return_value=[]):
            await service.on_startup()
            await service.on_shutdown()

        mock_sub.unsubscribe.assert_awaited_once()
        mock_client.close.assert_awaited_once()
        assert service.messaging is None
        assert service._dataset == []
