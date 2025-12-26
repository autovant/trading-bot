import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.alerts.base import AlertSink
from src.config import CrisisModeConfig, PerpsConfig, TradingConfig
from src.exchanges.zoomex_v3 import Precision
from src.risk.risk_manager import RiskManager
from src.services.perps import PerpsService


@pytest.mark.asyncio
async def test_check_position_pnl_runs_when_flat_and_updates_tracker():
    config = PerpsConfig(enabled=True, symbol="SOLUSDT", interval="5")
    trading = TradingConfig()
    crisis = CrisisModeConfig()
    client = AsyncMock()
    now = datetime.now(timezone.utc)
    client.get_closed_pnl = AsyncMock(
        side_effect=[
            {"list": []},
            {
                "list": [
                    {
                        "closedPnl": "-10.0",
                        "createdTime": int(now.timestamp() * 1000),
                    }
                ]
            },
        ]
    )

    service = PerpsService(
        config,
        client,
        trading_config=trading,
        crisis_config=crisis,
    )

    await service._check_position_pnl()
    assert service.last_position_check_time is not None
    assert service.pnl_tracker.trade_history == []

    service.last_position_check_time = datetime.now(timezone.utc) - timedelta(
        minutes=10
    )
    service.equity_usdt = 1000.0
    await service._check_position_pnl()

    assert len(service.pnl_tracker.trade_history) == 1
    assert service.pnl_tracker.trade_history[0]["pnl"] == -10.0
    assert service.pnl_tracker.consecutive_losses == 1
    assert client.get_closed_pnl.await_count == 2


def _build_service(perps_kwargs=None, alert_sink=None):
    config_kwargs = perps_kwargs or {}
    config = PerpsConfig(enabled=True, symbol="SOLUSDT", interval="5", **config_kwargs)
    trading = TradingConfig()
    crisis = CrisisModeConfig()
    return PerpsService(
        config,
        AsyncMock(),
        trading_config=trading,
        crisis_config=crisis,
        alert_sink=alert_sink,
    )


@pytest.mark.asyncio
async def test_check_session_limits_no_limits():
    service = _build_service()
    service.session_start_time = datetime.now(timezone.utc)
    assert await service._check_session_limits()


@pytest.mark.asyncio
async def test_check_session_limits_trade_limit(caplog):
    service = _build_service({"sessionMaxTrades": 1})
    service.session_start_time = datetime.now(timezone.utc)
    service.session_trades = 1

    with caplog.at_level(logging.WARNING):
        allowed = await service._check_session_limits()

    assert not allowed
    assert "SAFETY_SESSION_TRADES" in caplog.text


@pytest.mark.asyncio
async def test_check_session_limits_runtime_limit(caplog):
    service = _build_service({"sessionMaxRuntimeMinutes": 1})
    service.session_start_time = datetime.now(timezone.utc) - timedelta(minutes=2)

    with caplog.at_level(logging.WARNING):
        allowed = await service._check_session_limits()

    assert not allowed
    assert "SAFETY_SESSION_RUNTIME" in caplog.text


@pytest.mark.asyncio
async def test_circuit_breaker_logs_tag(caplog):
    service = _build_service({"consecutiveLossLimit": 1})
    service.pnl_tracker.consecutive_losses = 1

    with caplog.at_level(logging.WARNING):
        allowed = await service._check_risk_limits()

    assert not allowed
    assert "SAFETY_CIRCUIT_BREAKER" in caplog.text


class DummyAlertSink(AlertSink):
    def __init__(self):
        self.calls = []

    async def send_alert(self, category, message, context=None):
        self.calls.append((category, message, context))


@pytest.mark.asyncio
async def test_alert_sink_invoked_on_circuit_breaker():
    sink = DummyAlertSink()
    service = _build_service({"consecutiveLossLimit": 1}, alert_sink=sink)
    service.pnl_tracker.consecutive_losses = 1
    allowed = await service._check_risk_limits()
    assert not allowed
    assert sink.calls
    assert sink.calls[0][0] == "safety_circuit_breaker"


def test_state_persistence_round_trip(tmp_path):
    state_file = tmp_path / "perps_state.json"
    service = _build_service({"stateFile": str(state_file)})
    service.pnl_tracker.peak_equity = 1500.0
    service.pnl_tracker.daily_pnl["2025-01-01"] = -25.0
    service.pnl_tracker.consecutive_losses = 3
    service._persist_state()

    service.pnl_tracker.peak_equity = 0.0
    service.pnl_tracker.daily_pnl.clear()
    service.pnl_tracker.consecutive_losses = 0

    service._load_persisted_state()
    assert service.pnl_tracker.peak_equity == 1500.0
    assert service.pnl_tracker.daily_pnl["2025-01-01"] == -25.0
    assert service.pnl_tracker.consecutive_losses == 3


@pytest.mark.asyncio
async def test_risk_manager_blocks_order_submission():
    config = PerpsConfig(enabled=True, symbol="SOLUSDT", interval="5", riskPct=0.005)
    trading = TradingConfig()
    crisis = CrisisModeConfig()
    risk_manager = RiskManager(
        starting_equity=1000.0,
        max_account_risk_pct=0.10,
        max_open_risk_pct=0.0001,
        max_symbol_risk_pct=0.0001,
    )
    client = AsyncMock()
    client.get_margin_info = AsyncMock(return_value={"marginRatio": 0.0, "found": True})
    client.set_leverage = AsyncMock()
    client.get_precision = AsyncMock(
        return_value=Precision(qty_step=0.001, min_qty=0.001)
    )
    client.create_market_with_brackets = AsyncMock(return_value={"orderId": "123"})

    service = PerpsService(
        config,
        client,
        trading_config=trading,
        crisis_config=crisis,
        risk_manager=risk_manager,
    )
    service.equity_usdt = 1000.0
    risk_manager.update_equity(1000.0)

    await service._enter_long(100.0, stop_loss_pct=0.01, risk_pct=0.005)

    assert client.create_market_with_brackets.await_count == 0
    assert risk_manager.total_open_risk == 0
