import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from src.config import CrisisModeConfig, PerpsConfig, TradingConfig
from src.exchanges.zoomex_v3 import ZoomexV3Client
from src.services.perps import PerpsService
from src.state.perps_state_store import PerpsState, save_perps_state

LOGGER_ENV = "SAFETY_SCENARIO_LOG"


@pytest.fixture
def scenario_log_handler(tmp_path):
    path_str = os.environ.get(LOGGER_ENV)
    path = Path(path_str) if path_str else tmp_path / "scenario.log"
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(path, mode="w", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)

    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    try:
        yield path
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(old_level)


def _build_service(
    *,
    perps_overrides: Optional[dict] = None,
) -> PerpsService:
    overrides = perps_overrides or {}
    config = PerpsConfig(
        enabled=True,
        exchange="zoomex",
        symbol="SOLUSDT",
        interval="5",
        useTestnet=True,
        **overrides,
    )
    trading = TradingConfig()
    crisis = CrisisModeConfig()
    session = AsyncMock()
    return PerpsService(config, session, trading_config=trading, crisis_config=crisis)


@pytest.mark.asyncio
async def test_safety_normal_testnet_session(scenario_log_handler):
    service = _build_service(
        perps_overrides={
            "sessionMaxTrades": 5,
            "sessionMaxRuntimeMinutes": 5,
        }
    )
    service.session_start_time = datetime.now(timezone.utc)
    service.equity_usdt = 10_000
    assert await service._check_session_limits()
    assert await service._check_risk_limits()
    logging.info("Scenario normal_testnet_session completed without safety triggers.")


@pytest.mark.asyncio
async def test_safety_session_trade_cap(scenario_log_handler):
    service = _build_service(
        perps_overrides={
            "sessionMaxTrades": 1,
            "sessionMaxRuntimeMinutes": 30,
        }
    )
    service.session_start_time = datetime.now(timezone.utc)
    service.session_trades = 1
    assert not await service._check_session_limits()


@pytest.mark.asyncio
async def test_safety_session_runtime_cap(scenario_log_handler):
    service = _build_service(
        perps_overrides={
            "sessionMaxTrades": 10,
            "sessionMaxRuntimeMinutes": 1,
        }
    )
    service.session_start_time = datetime.now(timezone.utc) - timedelta(minutes=2)
    assert not await service._check_session_limits()


@pytest.mark.asyncio
async def test_safety_margin_block(scenario_log_handler):
    service = _build_service(
        perps_overrides={
            "maxMarginRatio": 0.10,
        }
    )
    service.equity_usdt = 1_000
    mock_client = AsyncMock()
    mock_client.get_margin_info = AsyncMock(
        return_value={"marginRatio": 0.50, "found": True}
    )
    service.exchange = mock_client
    await service._enter_long(
        price=100.0,
        entry_bar_time=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_safety_risk_limiters(scenario_log_handler):
    service = _build_service(perps_overrides={"consecutiveLossLimit": 1})
    service.session_start_time = datetime.now(timezone.utc)
    service.equity_usdt = 1_000
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    service.pnl_tracker.consecutive_losses = 5
    service.reconciliation_block_active = False
    assert not await service._check_risk_limits()

    service.pnl_tracker.consecutive_losses = 0
    service.pnl_tracker.daily_pnl[today] = -200.0
    assert not await service._check_risk_limits()

    service.pnl_tracker.daily_pnl[today] = 0.0
    service.pnl_tracker.peak_equity = 1_200.0
    service.equity_usdt = 800.0
    assert not await service._check_risk_limits()


@pytest.mark.asyncio
async def test_safety_reconciliation_guard(scenario_log_handler):
    service = _build_service()
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value={
            "list": [
                {
                    "symbol": service.config.symbol,
                    "positionIdx": service.config.positionIdx,
                    "size": "1",
                    "avgPrice": "100",
                    "unrealisedPnl": "5",
                    "side": "Sell",
                }
            ]
        }
    )
    service.exchange = mock_client
    await service._reconcile_positions()
    assert service.reconciliation_block_active


@pytest.mark.asyncio
async def test_safety_reconciliation_adopt_long(scenario_log_handler):
    service = _build_service()
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value={
            "list": [
                {
                    "symbol": service.config.symbol,
                    "positionIdx": service.config.positionIdx,
                    "size": "2",
                    "avgPrice": "150",
                    "unrealisedPnl": "10",
                    "side": "Buy",
                }
            ]
        }
    )
    service.exchange = mock_client
    await service._reconcile_positions()
    assert service.current_position_qty == 2
    assert not service.reconciliation_block_active


@pytest.mark.asyncio
async def test_safety_rate_limit(scenario_log_handler):
    session = AsyncMock()
    client = ZoomexV3Client(
        session,
        require_auth=False,
        max_requests_per_second=1000,
        max_requests_per_minute=100,
    )
    now = time.time()
    client._last_request_time = now
    await client._rate_limit()


@pytest.mark.asyncio
async def test_safety_state_persistence(tmp_path, scenario_log_handler):
    state_path = tmp_path / "perps_state.json"
    save_perps_state(
        state_path,
        PerpsState(
            peak_equity=2000.0,
            daily_pnl_by_date={"2099-01-01": -50.0},
            consecutive_losses=5,
        ),
    )
    service = _build_service(
        perps_overrides={
            "stateFile": str(state_path),
            "consecutiveLossLimit": 1,
        }
    )
    service._load_persisted_state()
    service.session_start_time = datetime.now(timezone.utc)
    service.equity_usdt = 1_000
    assert not await service._check_risk_limits()
