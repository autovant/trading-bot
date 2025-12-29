import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest

from src.alerts.manager import AlertManager
from src.config import PerpsConfig, TradingBotConfig, _assert_no_literal_secrets
from src.database import DatabaseManager
from src.engine.execution import ExecutionEngine
from src.engine.order_intent_ledger import OrderIntentLedger
from src.position_manager import PositionManager
from src.risk.risk_manager import RiskManager
from src.risk_manager import RiskManager as LegacyRiskManager
from src.services.perps import PerpsService


class TimeoutExchange:
    def __init__(self) -> None:
        self.place_calls = 0

    async def place_order(self, **_: Any) -> None:
        self.place_calls += 1
        raise asyncio.TimeoutError("timeout")

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        return []

    async def get_recent_trades(self) -> List[Dict[str, Any]]:
        return []


class OpenOrderExchange:
    def __init__(self, open_orders: List[Dict[str, Any]]) -> None:
        self.open_orders = open_orders
        self.place_calls = 0

    async def place_order(self, **_: Any) -> None:
        self.place_calls += 1
        return None

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        return self.open_orders

    async def get_recent_trades(self) -> List[Dict[str, Any]]:
        return []


class PerpsExchangeStub:
    def __init__(self, open_orders: List[Dict[str, Any]], fills: List[Dict[str, Any]]):
        self._open_orders = open_orders
        self._fills = fills

    async def get_open_orders(self, _: str) -> Dict[str, Any]:
        return {"list": self._open_orders}

    async def get_fills(self, _: str) -> Dict[str, Any]:
        return {"list": self._fills}

    async def sync_time(self) -> int:
        return 0


class TimeSkewExchange:
    def __init__(self, offset_ms: int) -> None:
        self.offset_ms = offset_ms

    async def sync_time(self) -> int:
        return self.offset_ms


def _write_config_files(tmp_path: Path) -> Dict[str, Path]:
    strategy = tmp_path / "strategy.yaml"
    risk = tmp_path / "risk.yaml"
    venues = tmp_path / "venues.yaml"
    for path in (strategy, risk, venues):
        path.write_text("{}")
    return {"strategy": strategy, "risk": risk, "venues": venues}


def _build_config(tmp_path: Path) -> TradingBotConfig:
    paths = _write_config_files(tmp_path)
    return TradingBotConfig(config_paths=paths)


@pytest.mark.asyncio
async def test_idempotent_submit_timeout_restart(tmp_path: Path) -> None:
    db = DatabaseManager("sqlite:///:memory:")
    await db.initialize()
    try:
        config = _build_config(tmp_path)
        exchange = TimeoutExchange()
        engine = ExecutionEngine(
            config=config,
            exchange=exchange,
            database=db,
            messaging=None,
            position_manager=PositionManager(),
            risk_manager=LegacyRiskManager(config),
            run_id="run-1",
            mode="paper",
        )

        await engine.place_order_directly(
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            quantity=1.0,
            price=100.0,
            idempotency_key="intent-1",
        )

        intent = await db.get_order_intent("intent-1")
        assert intent is not None
        assert intent.status == "submitted"

        open_orders = [
            {
                "id": "order-1",
                "clientOrderId": intent.client_id,
            }
        ]
        exchange_restart = OpenOrderExchange(open_orders)
        engine_restart = ExecutionEngine(
            config=config,
            exchange=exchange_restart,
            database=db,
            messaging=None,
            position_manager=PositionManager(),
            risk_manager=LegacyRiskManager(config),
            run_id="run-1",
            mode="paper",
        )

        await engine_restart.place_order_directly(
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            quantity=1.0,
            price=100.0,
            idempotency_key="intent-1",
        )

        assert exchange_restart.place_calls == 0
        refreshed = await db.get_order_intent("intent-1")
        assert refreshed is not None
        assert refreshed.status == "acked"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_restart_reconcile_open_orders(tmp_path: Path) -> None:
    db = DatabaseManager("sqlite:///:memory:")
    await db.initialize()
    try:
        config = _build_config(tmp_path)
        ledger = OrderIntentLedger(database=db, mode="paper", run_id="run-2")
        intent = await ledger.create_intent(
            idempotency_key="intent-2",
            client_id="client-2",
            symbol="ETH/USDT",
            side="buy",
            order_type="limit",
            quantity=2.0,
            price=200.0,
            stop_price=None,
            reduce_only=False,
        )

        open_orders = [{"id": "order-2", "clientOrderId": intent.client_id}]
        exchange = OpenOrderExchange(open_orders)
        engine = ExecutionEngine(
            config=config,
            exchange=exchange,
            database=db,
            messaging=None,
            position_manager=PositionManager(),
            risk_manager=LegacyRiskManager(config),
            run_id="run-2",
            mode="paper",
        )

        await engine.reconcile_startup()

        refreshed = await db.get_order_intent("intent-2")
        assert refreshed is not None
        assert refreshed.status == "acked"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_partial_fill_updates_position_and_risk(tmp_path: Path) -> None:
    db = DatabaseManager("sqlite:///:memory:")
    await db.initialize()
    try:
        config = PerpsConfig(enabled=True, symbol="BTCUSDT")
        open_orders = [{"orderLinkId": "client-3", "orderId": "order-3"}]
        fills = [{"orderLinkId": "client-3", "execId": "fill-1", "execQty": 4, "execPrice": 100}]
        exchange = PerpsExchangeStub(open_orders, fills)
        risk_manager = RiskManager(
            starting_equity=1000.0,
            max_account_risk_pct=0.2,
            max_open_risk_pct=0.2,
            max_symbol_risk_pct=0.2,
        )
        perps = PerpsService(
            config=config,
            exchange=exchange,
            alert_sink=AlertManager(),
            risk_manager=risk_manager,
            database=db,
            config_id="run-3",
            mode_name="paper",
        )

        intent, _ = await perps.intent_ledger.get_or_create_intent(
            idempotency_key="intent-3",
            client_id="client-3",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=10.0,
            price=100.0,
            stop_price=None,
            reduce_only=False,
        )
        await perps.intent_ledger.update_intent_status(intent, status="acked")

        await perps._reconcile_open_orders(reason="test")

        assert perps.current_position_qty == 4.0
        assert risk_manager.open_risk_by_symbol["BTCUSDT"] == pytest.approx(2.0)
        refreshed = await db.get_order_intent("intent-3")
        assert refreshed is not None
        assert refreshed.status == "partially_filled"
    finally:
        await db.close()


def test_stale_data_blocks_entries() -> None:
    config = PerpsConfig(enabled=True, symbol="BTCUSDT")
    perps = PerpsService(config=config, exchange=PerpsExchangeStub([], []))
    ts = datetime.now(timezone.utc) - timedelta(seconds=500)
    df = pd.DataFrame(
        [{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        index=[ts],
    )
    assert perps._handle_stale_data(df, perps.interval_delta, label="LTF")
    assert perps.data_stale_block_active is True


@pytest.mark.asyncio
async def test_time_drift_halts_entries() -> None:
    config = PerpsConfig(enabled=True, symbol="BTCUSDT", timeSyncMaxSkewMs=10)
    perps = PerpsService(config=config, exchange=TimeSkewExchange(100))
    await perps._sync_time_or_halt()
    assert perps.reconciliation_block_active is True


def test_mode_mismatch_live_testnet_fails(tmp_path: Path) -> None:
    paths = _write_config_files(tmp_path)
    with pytest.raises(ValueError):
        TradingBotConfig(
            app_mode="live",
            exchange={"testnet": True},
            perps={"useTestnet": True},
            config_paths=paths,
        )


def test_secrets_in_yaml_rejected() -> None:
    with pytest.raises(ValueError):
        _assert_no_literal_secrets(
            {"exchange": {"api_key": "plain", "secret_key": "secret"}}
        )
