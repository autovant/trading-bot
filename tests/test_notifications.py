"""Tests for src/notifications/ — Discord, Telegram, and Escalation."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.notifications.discord import DiscordNotifier
from src.notifications.escalation import AlertEscalator, Alarm, Severity
from src.notifications.telegram import TelegramNotifier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def discord():
    return DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test/token")


@pytest.fixture
def discord_no_url():
    return DiscordNotifier(webhook_url="")


@pytest.fixture
def telegram():
    return TelegramNotifier(bot_token="123:ABC", chat_id="999")


@pytest.fixture
def telegram_no_creds():
    return TelegramNotifier(bot_token="", chat_id="")


@pytest.fixture
def escalator():
    return AlertEscalator(escalation_delay_seconds=0.1)


# ---------------------------------------------------------------------------
# Discord tests
# ---------------------------------------------------------------------------

class TestDiscordSend:
    """Test DiscordNotifier.send()."""

    async def test_send_success(self, discord):
        """Mock httpx, verify webhook payload has correct embed structure."""
        mock_response = httpx.Response(204, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await discord.send("Test Title", "Test body", severity="info")
            assert result is True

            call_kwargs = mock_post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert "embeds" in payload
            embed = payload["embeds"][0]
            assert embed["title"] == "Test Title"
            assert embed["description"] == "Test body"
            assert embed["color"] == DiscordNotifier.COLORS["info"]
            assert "timestamp" in embed

    async def test_send_with_fields_and_footer(self, discord):
        """Verify fields and footer are included in embed payload."""
        mock_response = httpx.Response(204, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            fields = [{"name": "Key", "value": "Val", "inline": False}]
            result = await discord.send("T", "D", fields=fields, footer="foot")
            assert result is True

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            embed = payload["embeds"][0]
            assert embed["fields"] == [{"name": "Key", "value": "Val", "inline": False}]
            assert embed["footer"] == {"text": "foot"}

    async def test_send_failure_status(self, discord):
        """Non-2xx response returns False."""
        mock_response = httpx.Response(400, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await discord.send("Fail", "body")
            assert result is False

    async def test_send_no_webhook_url(self, discord_no_url):
        """No URL configured → skip silently, return False."""
        result = await discord_no_url.send("Title", "body")
        assert result is False

    async def test_send_network_error(self, discord):
        """HTTP exception returns False gracefully."""
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, side_effect=httpx.ConnectError("fail")):
            result = await discord.send("Title", "body")
            assert result is False


class TestDiscordTradeReport:
    """Test DiscordNotifier.trade_report()."""

    async def test_trade_report_formats_fields(self, discord):
        """Verify trade notification includes symbol, side, qty, price, pnl."""
        mock_response = httpx.Response(204, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await discord.trade_report("BTCUSDT", "buy", 0.5, 50000.0, pnl=150.0)
            assert result is True

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            embed = payload["embeds"][0]
            field_names = [f["name"] for f in embed["fields"]]
            assert "Symbol" in field_names
            assert "Side" in field_names
            assert "Qty" in field_names
            assert "Price" in field_names
            assert "P&L" in field_names

            side_field = next(f for f in embed["fields"] if f["name"] == "Side")
            assert side_field["value"] == "BUY"

    async def test_trade_report_positive_pnl_is_success(self, discord):
        """Positive P&L uses 'success' severity (green color)."""
        mock_response = httpx.Response(204, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await discord.trade_report("ETHUSDT", "sell", 1.0, 3000.0, pnl=50.0)
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            assert payload["embeds"][0]["color"] == DiscordNotifier.COLORS["success"]

    async def test_trade_report_negative_pnl_is_warning(self, discord):
        """Negative P&L uses 'warning' severity."""
        mock_response = httpx.Response(204, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await discord.trade_report("ETHUSDT", "sell", 1.0, 3000.0, pnl=-20.0)
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            assert payload["embeds"][0]["color"] == DiscordNotifier.COLORS["warning"]

    async def test_trade_report_no_pnl(self, discord):
        """When pnl is None, P&L field is omitted."""
        mock_response = httpx.Response(204, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await discord.trade_report("BTCUSDT", "buy", 0.1, 40000.0)
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            field_names = [f["name"] for f in payload["embeds"][0]["fields"]]
            assert "P&L" not in field_names


class TestDiscordDailySummary:
    """Test DiscordNotifier.daily_summary()."""

    async def test_daily_summary_formats_stats(self, discord):
        """Verify daily stats include total_trades, win_rate, pnl, equity, max_dd."""
        mock_response = httpx.Response(204, request=httpx.Request("POST", "https://x"))
        stats = {
            "total_trades": 42,
            "win_rate": 0.65,
            "realized_pnl": 1234.56,
            "equity": 50000.0,
            "max_drawdown": 0.03,
        }
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await discord.daily_summary(stats)
            assert result is True

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            embed = payload["embeds"][0]
            field_names = [f["name"] for f in embed["fields"]]
            assert "Total Trades" in field_names
            assert "Win Rate" in field_names
            assert "P&L" in field_names
            assert "Equity" in field_names
            assert "Max DD" in field_names
            assert embed["footer"] is not None


# ---------------------------------------------------------------------------
# Telegram tests
# ---------------------------------------------------------------------------

class TestTelegramSend:
    """Test TelegramNotifier.send()."""

    async def test_send_success(self, telegram):
        """Mock httpx, verify Telegram Bot API call format."""
        mock_response = httpx.Response(200, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await telegram.send("Hello", "World", severity="warning")
            assert result is True

            call_args = mock_post.call_args
            url = call_args.args[0] if call_args.args else call_args[0][0]
            assert "api.telegram.org/bot123:ABC/sendMessage" in url

            payload = call_args.kwargs.get("json") or call_args[1]["json"]
            assert payload["chat_id"] == "999"
            assert payload["parse_mode"] == "HTML"
            assert payload["disable_web_page_preview"] is True
            assert "⚠️" in payload["text"]  # warning emoji
            assert "<b>" in payload["text"]  # bold title

    async def test_send_no_credentials(self, telegram_no_creds):
        """Missing bot_token/chat_id → skip silently."""
        result = await telegram_no_creds.send("Title", "body")
        assert result is False

    async def test_send_api_error(self, telegram):
        """Non-200 Telegram API response returns False."""
        mock_response = httpx.Response(403, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await telegram.send("Title", "body")
            assert result is False

    async def test_send_network_error(self, telegram):
        """HTTP exception returns False gracefully."""
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, side_effect=httpx.ConnectError("fail")):
            result = await telegram.send("Title", "body")
            assert result is False

    async def test_send_html_escaping(self, telegram):
        """HTML special chars in title/message are escaped."""
        mock_response = httpx.Response(200, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await telegram.send("<script>", "a & b < c")
            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            assert "<script>" not in payload["text"]
            assert "&lt;script&gt;" in payload["text"]
            assert "a &amp; b &lt; c" in payload["text"]


class TestTelegramTradeReport:
    """Test TelegramNotifier.trade_report()."""

    async def test_trade_report_formats_fields(self, telegram):
        """Verify trade notification includes symbol, side, qty, price, pnl."""
        mock_response = httpx.Response(200, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await telegram.trade_report("BTCUSDT", "buy", 0.5, 50000.0, pnl=150.0)
            assert result is True

            payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
            text = payload["text"]
            assert "BTCUSDT" in text
            assert "BUY" in text
            assert "P&amp;L" in text  # HTML-escaped


# ---------------------------------------------------------------------------
# Escalation tests
# ---------------------------------------------------------------------------

class TestEscalationRaiseAlarm:
    """Test AlertEscalator.raise_alarm()."""

    async def test_raise_alarm_creates_alarm(self, escalator):
        """Raise an alarm and verify it's tracked."""
        alarm = await escalator.raise_alarm("test-1", "Test", "Something happened", Severity.WARNING)
        assert alarm.alarm_id == "test-1"
        assert alarm.severity == Severity.WARNING
        assert alarm.acknowledged is False
        assert len(escalator.active_alarms) == 1

    async def test_raise_alarm_idempotent_same_severity(self, escalator):
        """Re-raising same alarm at same severity doesn't duplicate."""
        a1 = await escalator.raise_alarm("dup", "Title", "msg", Severity.WARNING)
        a2 = await escalator.raise_alarm("dup", "Title", "msg", Severity.WARNING)
        assert a1 is a2
        assert len(escalator.active_alarms) == 1

    async def test_raise_alarm_escalates_to_higher_severity(self, escalator):
        """Re-raising at higher severity escalates the alarm."""
        alarm = await escalator.raise_alarm("esc", "Title", "msg", Severity.WARNING)
        assert alarm.severity == Severity.WARNING
        alarm = await escalator.raise_alarm("esc", "Title", "critical now", Severity.CRITICAL)
        assert alarm.severity == Severity.CRITICAL
        assert alarm.escalation_count == 1

    async def test_raise_alarm_critical_callback(self):
        """CRITICAL alarm triggers on_critical callback."""
        cb = AsyncMock()
        esc = AlertEscalator(on_critical=cb)
        await esc.raise_alarm("crit-1", "Title", "msg", Severity.CRITICAL)
        cb.assert_awaited_once()
        assert cb.call_args[0][0].alarm_id == "crit-1"
        await esc.shutdown()

    async def test_raise_alarm_shutdown_callback(self):
        """AUTO_SHUTDOWN alarm triggers both on_critical and on_shutdown."""
        cb_crit = AsyncMock()
        cb_shut = AsyncMock()
        esc = AlertEscalator(on_critical=cb_crit, on_shutdown=cb_shut)
        await esc.raise_alarm("shut-1", "Title", "msg", Severity.AUTO_SHUTDOWN)
        cb_crit.assert_awaited_once()
        cb_shut.assert_awaited_once()
        await esc.shutdown()


class TestEscalationAcknowledge:
    """Test AlertEscalator.acknowledge()."""

    async def test_acknowledge_stops_alarm(self, escalator):
        """Raise + acknowledge → alarm marked acknowledged, removed from active."""
        await escalator.raise_alarm("ack-1", "Title", "msg", Severity.WARNING)
        assert len(escalator.active_alarms) == 1

        result = await escalator.acknowledge("ack-1", by="operator")
        assert result is True
        alarm = escalator.get_alarm("ack-1")
        assert alarm.acknowledged is True
        assert alarm.acknowledged_by == "operator"
        assert alarm.acknowledged_at is not None
        assert len(escalator.active_alarms) == 0

    async def test_acknowledge_nonexistent(self, escalator):
        """Acknowledging unknown alarm_id returns False."""
        result = await escalator.acknowledge("nonexistent")
        assert result is False

    async def test_acknowledge_already_acknowledged(self, escalator):
        """Double-acknowledgement returns False."""
        await escalator.raise_alarm("dup-ack", "T", "m", Severity.WARNING)
        await escalator.acknowledge("dup-ack")
        result = await escalator.acknowledge("dup-ack")
        assert result is False


class TestEscalationSeverityLevels:
    """Test all four severity levels: INFO, WARNING, CRITICAL, AUTO_SHUTDOWN."""

    async def test_info_no_escalation(self):
        """INFO alarm does not trigger critical/shutdown callbacks or timers."""
        cb_crit = AsyncMock()
        cb_shut = AsyncMock()
        esc = AlertEscalator(on_critical=cb_crit, on_shutdown=cb_shut)
        alarm = await esc.raise_alarm("info-1", "Info", "msg", Severity.INFO)
        assert alarm.severity == Severity.INFO
        cb_crit.assert_not_awaited()
        cb_shut.assert_not_awaited()
        await esc.shutdown()

    async def test_warning_auto_escalates_to_critical(self):
        """Unacknowledged WARNING escalates to CRITICAL after delay."""
        cb_crit = AsyncMock()
        esc = AlertEscalator(escalation_delay_seconds=0.05, on_critical=cb_crit)
        await esc.raise_alarm("w-1", "Warn", "msg", Severity.WARNING)

        await asyncio.sleep(0.15)  # wait for escalation

        alarm = esc.get_alarm("w-1")
        assert alarm.severity == Severity.CRITICAL
        cb_crit.assert_awaited_once()
        await esc.shutdown()

    async def test_warning_acknowledged_before_escalation(self):
        """Acknowledging WARNING before timer prevents escalation."""
        cb_crit = AsyncMock()
        esc = AlertEscalator(escalation_delay_seconds=0.2, on_critical=cb_crit)
        await esc.raise_alarm("w-2", "Warn", "msg", Severity.WARNING)
        await esc.acknowledge("w-2")

        await asyncio.sleep(0.3)

        alarm = esc.get_alarm("w-2")
        assert alarm.severity == Severity.WARNING  # not escalated
        cb_crit.assert_not_awaited()
        await esc.shutdown()

    async def test_severity_ordering(self):
        """Severity enum values are ordered: INFO < WARNING < CRITICAL < AUTO_SHUTDOWN."""
        assert Severity.INFO < Severity.WARNING < Severity.CRITICAL < Severity.AUTO_SHUTDOWN

    async def test_list_alarms_includes_acknowledged(self, escalator):
        """list_alarms(include_acknowledged=True) returns all alarms."""
        await escalator.raise_alarm("a", "T", "m", Severity.INFO)
        await escalator.raise_alarm("b", "T", "m", Severity.WARNING)
        await escalator.acknowledge("a")
        assert len(escalator.list_alarms(include_acknowledged=False)) == 1
        assert len(escalator.list_alarms(include_acknowledged=True)) == 2
