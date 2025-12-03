import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.config import CrisisModeConfig, PerpsConfig, TradingConfig
from src.services.perps import PerpsService
from src.state.symbol_health_store import SymbolHealthStore, _format_iso


def _build_service(monkeypatch, warning_size_multiplier=1.0):
    config = PerpsConfig(enabled=True, symbol="BTCUSDT", interval="5", riskPct=0.01, stopLossPct=0.01)
    service = PerpsService(
        config,
        AsyncMock(),
        trading_config=TradingConfig(),
        crisis_config=CrisisModeConfig(),
        warning_size_multiplier=warning_size_multiplier,
    )
    service.equity_usdt = 1000.0

    client = AsyncMock()
    client.get_margin_info = AsyncMock(return_value={"marginRatio": 0.0, "found": True})
    client.set_leverage = AsyncMock()
    client.get_precision = AsyncMock(return_value=SimpleNamespace(min_qty=0.0001))
    service.client = client

    monkeypatch.setattr("src.services.perps.risk_position_size", lambda **kwargs: 2.0)
    monkeypatch.setattr("src.services.perps.round_quantity", lambda qty, precision: qty)
    enter_mock = AsyncMock(return_value={"orderId": "123"})
    monkeypatch.setattr("src.services.perps.enter_long_with_brackets", enter_mock)

    return service, enter_mock, client


@pytest.mark.asyncio
async def test_runtime_health_ok_allows_orders(monkeypatch, tmp_path):
    service, enter_mock, client = _build_service(monkeypatch)
    store = SymbolHealthStore(tmp_path / "health.json")
    store.update_symbol_state("BTCUSDT", status="OK", reasons=[], blocked_until=None)
    service.set_symbol_health_store(store)

    await service._enter_long(price=100.0, stop_loss_pct=0.01, risk_pct=0.01)

    assert enter_mock.await_count == 1
    assert client.get_margin_info.await_count == 1


@pytest.mark.asyncio
async def test_runtime_health_blocks_failing(monkeypatch, tmp_path):
    service, enter_mock, client = _build_service(monkeypatch)
    store = SymbolHealthStore(tmp_path / "health.json")
    store.update_symbol_state(
        "BTCUSDT",
        status="FAILING",
        reasons=["drawdown"],
        blocked_until=_format_iso(datetime.now(timezone.utc) + timedelta(minutes=5)),
    )
    service.set_symbol_health_store(store)

    await service._enter_long(price=100.0, stop_loss_pct=0.01, risk_pct=0.01)

    assert enter_mock.await_count == 0
    assert client.get_margin_info.await_count == 0


@pytest.mark.asyncio
async def test_runtime_health_warning_scales_size(monkeypatch, tmp_path):
    service, enter_mock, _ = _build_service(monkeypatch, warning_size_multiplier=0.5)
    store = SymbolHealthStore(tmp_path / "health.json")
    store.update_symbol_state("BTCUSDT", status="WARNING", reasons=["volatility"], blocked_until=None)
    service.set_symbol_health_store(store, warning_size_multiplier=0.5)

    await service._enter_long(price=100.0, stop_loss_pct=0.01, risk_pct=0.01)

    assert enter_mock.await_count == 1
    assert enter_mock.await_args.kwargs["qty"] == 1.0
