import asyncio
from datetime import datetime

import pytest

from src.config import PaperConfig
from src.paper_trader import MarketSnapshot, PaperBroker


class StubDatabase:
    def __init__(self):
        self.trades = []
        self.orders = {}
        self.pnls = []
        self.positions = {}
        self.created_orders = []

    async def create_order(self, order):
        self.created_orders.append(order)
        self.orders.setdefault(order.client_id, []).append(order.status)
        return len(self.created_orders)

    async def create_trade(self, trade):
        self.trades.append(trade)
        return len(self.trades)

    async def update_order_status(self, order_id, status, is_shadow=False):
        self.orders.setdefault(order_id, []).append(status)
        return True

    async def add_pnl_entry(self, entry):
        self.pnls.append(entry)
        return len(self.pnls)

    async def update_position(self, position):
        self.positions[position.symbol] = position
        return True


def basic_config(**overrides) -> PaperConfig:
    cfg_dict = {
        "fee_bps": 7,
        "maker_rebate_bps": -1,
        "funding_enabled": True,
        "slippage_bps": 3,
        "max_slippage_bps": 10,
        "spread_slippage_coeff": 0.0,
        "ofi_slippage_coeff": 0.0,
        "latency_ms": {"mean": 0, "p95": 0},
        "partial_fill": {
            "enabled": False,
            "min_slice_pct": 0.15,
            "max_slices": 1,
        },
        "price_source": "live",
        "seed": 42,
    }
    cfg_dict.update(overrides)
    return PaperConfig(**cfg_dict)


def make_snapshot(price: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        best_bid=price - 0.5,
        best_ask=price + 0.5,
        bid_size=25,
        ask_size=20,
        last_price=price,
        last_side="buy",
        last_size=1.5,
        funding_rate=0.0001,
        timestamp=datetime.utcnow(),
    )


@pytest.mark.asyncio
async def test_market_order_slippage_and_fees():
    db = StubDatabase()
    broker = PaperBroker(
        config=basic_config(),
        database=db,
        mode="paper",
        run_id="test-run",
        initial_balance=10_000,
    )
    await broker.update_market(make_snapshot(100))
    await broker.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=1.0,
        client_id="test-market",
    )
    await broker.update_market(make_snapshot(100))
    await asyncio.sleep(0.05)  # allow fill task

    assert db.trades, "trade not recorded"
    trade = db.trades[-1]
    expected_price = (100 + 0.5) * (1 + 0.0003)
    assert pytest.approx(trade.price, rel=1e-6) == expected_price
    expected_fee = expected_price * 1.0 * (7 / 10_000)
    assert pytest.approx(trade.fees, rel=1e-6) == expected_fee
    assert trade.mode == "paper"
    assert not trade.maker


@pytest.mark.asyncio
async def test_limit_order_partial_fill():
    db = StubDatabase()
    cfg = basic_config(
        partial_fill={
            "enabled": True,
            "min_slice_pct": 0.2,
            "max_slices": 3,
        },
        seed=123,
    )
    broker = PaperBroker(
        config=cfg, database=db, mode="paper", run_id="test-run", initial_balance=10_000
    )
    await broker.update_market(make_snapshot(100))
    await broker.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="limit",
        quantity=1.2,
        price=100.5,
        client_id="limit-maker",
    )
    await asyncio.sleep(0.05)

    statuses = db.orders.get("limit-maker", [])
    assert statuses, "order status not updated"
    assert statuses[-1] == "filled"
    # Multiple fills recorded
    fills = [t for t in db.trades if t.order_id == "limit-maker"]
    assert len(fills) >= 1
    total_qty = sum(t.quantity for t in fills)
    assert pytest.approx(total_qty, rel=1e-6) == 1.2
    assert all(t.maker for t in fills)


@pytest.mark.asyncio
async def test_stop_order_triggers_on_mid_cross():
    db = StubDatabase()
    broker = PaperBroker(
        config=basic_config(),
        database=db,
        mode="paper",
        run_id="run",
        initial_balance=5_000,
    )
    await broker.update_market(make_snapshot(100))
    await broker.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="stop",
        quantity=0.5,
        stop_price=99.0,
        client_id="stop-order",
    )
    await broker.update_market(make_snapshot(98.5))
    await asyncio.sleep(0.01)

    orders = db.orders.get("stop-order", [])
    assert orders[-1] == "filled"
    trades = [t for t in db.trades if t.order_id == "stop-order"]
    assert trades, "stop order did not produce trade"
    assert not any(t.maker for t in trades)


def test_slippage_boundaries():
    db = StubDatabase()
    cfg = basic_config(
        max_slippage_bps=12, ofi_slippage_coeff=0.5, spread_slippage_coeff=0.3
    )
    broker = PaperBroker(
        config=cfg, database=db, mode="paper", run_id="run", initial_balance=1_000
    )
    snapshot = make_snapshot(100)
    snapshot.order_flow_imbalance = 5.0
    sl = broker._compute_slippage_bps(snapshot, "buy")
    assert 0 <= sl <= cfg.max_slippage_bps


def test_latency_sampler_properties():
    db = StubDatabase()
    cfg = basic_config(latency_ms={"mean": 100, "p95": 250})
    broker = PaperBroker(
        config=cfg, database=db, mode="paper", run_id="run", initial_balance=1_000
    )
    samples = sorted(broker._sample_latency_ms() for _ in range(1_000))
    assert samples[0] >= 0
    index = int(0.95 * (len(samples) - 1))
    p95 = float(samples[index])
    assert pytest.approx(p95, rel=0.2) == cfg.latency_ms.p95


@pytest.mark.asyncio
async def test_liquidation_guard_rejects_insufficient_buffer():
    db = StubDatabase()
    cfg = basic_config(
        initial_margin_pct=0.02,
        maintenance_margin_pct=0.005,
        max_leverage=50,
    )
    broker = PaperBroker(
        config=cfg, database=db, mode="paper", run_id="guard", initial_balance=10_000
    )
    await broker.update_market(make_snapshot(100))
    await broker.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=1.0,
        client_id="guarded-order",
    )
    await asyncio.sleep(0.05)

    statuses = db.orders.get("guarded-order", [])
    assert statuses, "order status not recorded"
    assert statuses[-1] == "rejected"
    assert not any(trade.order_id == "guarded-order" for trade in db.trades)
