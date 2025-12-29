import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.config import ConfigPaths, ExchangeConfig, PerpsConfig, TradingBotConfig, load_config
from src.database import DatabaseManager, OrderIntent
from src.engine.execution import ExecutionEngine
from src.models import OrderResponse
from src.position_manager import PositionManager
from src.risk_manager import RiskManager
from src.services.perps import PerpsService
from src.exchanges.zoomex_v3 import ZoomexError, ZoomexV3Client


class StubExchange:
    def __init__(self) -> None:
        self.place_calls = 0
        self.open_orders = []
        self.trades = []

    async def place_order(
        self,
        *,
        symbol,
        side,
        order_type,
        quantity,
        price=None,
        stop_price=None,
        reduce_only=False,
        client_id=None,
        is_shadow=False,
    ):
        self.place_calls += 1
        order_id = f"order-{self.place_calls}"
        self.open_orders.append(
            {"id": order_id, "clientOrderId": client_id, "symbol": symbol}
        )
        if self.place_calls == 1:
            raise asyncio.TimeoutError("submit timeout")
        return OrderResponse(
            order_id=order_id,
            client_id=client_id or order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price or 0.0,
            status="open",
            mode="live",
            timestamp=datetime.now(timezone.utc),
        )

    async def get_open_orders(self, symbol=None):
        return self.open_orders

    async def get_recent_trades(self, symbol=None):
        return self.trades


def _make_config(tmp_path: Path, *, app_mode: str = "live") -> TradingBotConfig:
    strategy = tmp_path / "strategy.yaml"
    risk = tmp_path / "risk.yaml"
    venues = tmp_path / "venues.yaml"
    strategy.write_text("{}", encoding="utf-8")
    risk.write_text("{}", encoding="utf-8")
    venues.write_text("{}", encoding="utf-8")
    return TradingBotConfig(
        app_mode=app_mode,
        exchange=ExchangeConfig(api_key="key", secret_key="secret", testnet=False),
        perps=PerpsConfig(useTestnet=False),
        config_paths=ConfigPaths(strategy=strategy, risk=risk, venues=venues),
    )


@pytest.mark.asyncio
async def test_idempotent_submit_restart_no_duplicate(tmp_path: Path):
    db = DatabaseManager(f"sqlite:///{tmp_path/'db.sqlite'}")
    await db.initialize()
    config = _make_config(tmp_path)
    exchange = StubExchange()
    engine = ExecutionEngine(
        config=config,
        exchange=exchange,
        database=db,
        messaging=None,
        position_manager=PositionManager(),
        risk_manager=RiskManager(config),
        run_id="run-1",
        mode="live",
    )

    await engine.place_order_directly(
        symbol="BTC/USDT",
        side="buy",
        order_type="limit",
        quantity=1.0,
        price=100.0,
        idempotency_key="intent-1",
    )
    assert exchange.place_calls == 1

    engine_restart = ExecutionEngine(
        config=config,
        exchange=exchange,
        database=db,
        messaging=None,
        position_manager=PositionManager(),
        risk_manager=RiskManager(config),
        run_id="run-1",
        mode="live",
    )
    await engine_restart.reconcile_startup()
    assert exchange.place_calls == 1

    intent = await db.get_order_intent("intent-1")
    assert intent is not None
    assert intent.status in {"submitted", "acked"}

    await db.close()


@pytest.mark.asyncio
async def test_partial_fill_updates_intent(tmp_path: Path):
    db = DatabaseManager(f"sqlite:///{tmp_path/'db.sqlite'}")
    await db.initialize()
    config = _make_config(tmp_path)
    exchange = StubExchange()
    engine = ExecutionEngine(
        config=config,
        exchange=exchange,
        database=db,
        messaging=None,
        position_manager=PositionManager(),
        risk_manager=RiskManager(config),
        run_id="run-2",
        mode="live",
    )

    intent = OrderIntent(
        idempotency_key="intent-2",
        client_id="client-2",
        order_id="order-2",
        symbol="BTC/USDT",
        side="buy",
        order_type="limit",
        quantity=10.0,
        price=100.0,
        status="acked",
        mode="live",
        run_id="run-2",
    )
    await db.create_order_intent(intent)
    exchange.trades = [
        {"id": "trade-1", "order": "order-2", "amount": 4.0, "price": 100.0}
    ]

    await engine.reconcile_startup()

    updated = await db.get_order_intent("intent-2")
    assert updated is not None
    assert updated.status == "partially_filled"
    assert updated.filled_qty == 4.0

    await db.close()


@pytest.mark.asyncio
async def test_stale_data_halts_perps(tmp_path: Path):
    config = PerpsConfig(maxDataStalenessSeconds=10, interval="1")
    db = DatabaseManager(f"sqlite:///{tmp_path/'db.sqlite'}")
    await db.initialize()
    service = PerpsService(
        config,
        exchange=StubExchange(),
        database=db,
        mode_name="paper",
    )
    now = datetime.now(timezone.utc)
    df = pd.DataFrame({"close": [1, 2, 3]}, index=[now - timedelta(minutes=10)] * 3)
    assert service._handle_stale_data(df, timedelta(minutes=1), label="LTF") is True
    assert service.data_stale_block_active is True
    await db.close()


@pytest.mark.asyncio
async def test_time_sync_halts_on_drift(tmp_path: Path):
    class DriftExchange:
        async def sync_time(self):
            return 5000

    config = PerpsConfig(timeSyncMaxSkewMs=1000)
    db = DatabaseManager(f"sqlite:///{tmp_path/'db.sqlite'}")
    await db.initialize()
    service = PerpsService(
        config,
        exchange=DriftExchange(),
        database=db,
        mode_name="live",
    )
    with pytest.raises(ZoomexError):
        await service._sync_time_or_halt()
    await db.close()


def test_mode_mismatch_rejected(tmp_path: Path):
    strategy = tmp_path / "strategy.yaml"
    risk = tmp_path / "risk.yaml"
    venues = tmp_path / "venues.yaml"
    strategy.write_text("{}", encoding="utf-8")
    risk.write_text("{}", encoding="utf-8")
    venues.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        TradingBotConfig(
            app_mode="live",
            exchange=ExchangeConfig(api_key="k", secret_key="s", testnet=True),
            config_paths=ConfigPaths(strategy=strategy, risk=risk, venues=venues),
        )


def test_secrets_in_yaml_rejected(tmp_path: Path, monkeypatch):
    strategy = tmp_path / "strategy.yaml"
    risk = tmp_path / "risk.yaml"
    venues = tmp_path / "venues.yaml"
    strategy.write_text(
        "exchange:\n  api_key: \"literal\"\n  secret_key: \"literal\"\n",
        encoding="utf-8",
    )
    risk.write_text("{}", encoding="utf-8")
    venues.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("STRATEGY_CFG", str(strategy))
    monkeypatch.setenv("RISK_CFG", str(risk))
    monkeypatch.setenv("VENUES_CFG", str(venues))
    with pytest.raises(ValueError):
        load_config()


@pytest.mark.asyncio
async def test_zoomex_time_sync_offset():
    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = ZoomexV3Client(
            session=session,
            api_key="key",
            api_secret="secret",
        )
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        offset = await client.sync_time(server_time_ms=now_ms + 500)
        assert 400 <= offset <= 600
