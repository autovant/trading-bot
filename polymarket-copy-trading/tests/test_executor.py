"""Tests for the executor."""

from __future__ import annotations

import pytest

from src.executor import Executor
from src.models import CopySignal, SourceTrade, TradeStatus, TradeSide


class MockPolymarketClient:
    """Mock client for testing executor."""

    def __init__(self, should_fail: bool = False):
        self._should_fail = should_fail
        self.orders_placed: list = []

    async def create_order(self, token_id, side, price, size):
        if self._should_fail:
            raise RuntimeError("Exchange error")
        order = {"order_id": "order-123", "status": "PLACED"}
        self.orders_placed.append(order)
        return order

    async def cancel_order(self, order_id):
        return True


def _make_signal(price: float = 0.5, size: float = 20.0) -> CopySignal:
    return CopySignal(
        source_trade=SourceTrade(
            trade_id="t1",
            wallet="0xabc",
            market_id="m1",
            asset_id="token-1",
            side=TradeSide.BUY,
            price=price,
            size=size,
        ),
        target_side=TradeSide.BUY,
        target_price=price,
        target_size=size,
    )


class TestExecutor:
    @pytest.mark.asyncio
    async def test_dry_run(self):
        client = MockPolymarketClient()
        executor = Executor(client, dry_run=True)
        result = await executor.execute(_make_signal())
        assert result.status == TradeStatus.FILLED
        assert result.fill_price == 0.5
        assert len(client.orders_placed) == 0  # no real orders in dry run

    @pytest.mark.asyncio
    async def test_live_execution(self):
        client = MockPolymarketClient()
        executor = Executor(client, dry_run=False)
        result = await executor.execute(_make_signal())
        assert result.status == TradeStatus.FILLED
        assert result.order_id == "order-123"
        assert len(client.orders_placed) == 1

    @pytest.mark.asyncio
    async def test_execution_failure(self):
        client = MockPolymarketClient(should_fail=True)
        executor = Executor(client, dry_run=False)
        result = await executor.execute(_make_signal())
        assert result.status == TradeStatus.FAILED
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_adjusted_size(self):
        client = MockPolymarketClient()
        executor = Executor(client, dry_run=True)
        result = await executor.execute(_make_signal(), adjusted_size=5.0)
        assert result.fill_size == 5.0
        assert result.size == 5.0
