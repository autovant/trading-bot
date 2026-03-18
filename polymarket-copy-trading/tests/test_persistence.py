"""Tests for the persistence layer."""

from __future__ import annotations

import pytest

from src.models import CopiedTrade, TradeStatus, TradeSide
from src.persistence import TradeStore


@pytest.fixture
async def store(tmp_path):
    """Provide a clean in-memory-like store for each test."""
    s = TradeStore(f"sqlite:///{tmp_path / 'test.db'}")
    await s.start()
    yield s
    await s.stop()


def _make_trade(**kwargs) -> CopiedTrade:
    defaults = dict(
        source_trade_id="st1",
        source_wallet="0xabc",
        market_id="m1",
        asset_id="a1",
        side=TradeSide.BUY,
        price=0.5,
        size=10.0,
        status=TradeStatus.FILLED,
    )
    defaults.update(kwargs)
    return CopiedTrade(**defaults)


class TestTradeStore:
    @pytest.mark.asyncio
    async def test_save_and_retrieve(self, store):
        trade = _make_trade()
        row_id = await store.save_trade(trade)
        assert row_id > 0

        trades = await store.get_recent_trades(10)
        assert len(trades) == 1
        assert trades[0].source_trade_id == "st1"
        assert trades[0].side == TradeSide.BUY

    @pytest.mark.asyncio
    async def test_multiple_trades(self, store):
        for i in range(5):
            await store.save_trade(_make_trade(source_trade_id=f"st{i}"))
        trades = await store.get_recent_trades(10)
        assert len(trades) == 5

    @pytest.mark.asyncio
    async def test_update_status(self, store):
        row_id = await store.save_trade(_make_trade(status=TradeStatus.PENDING))
        await store.update_trade_status(row_id, TradeStatus.FILLED, fill_price=0.55)
        trades = await store.get_recent_trades(1)
        assert trades[0].status == TradeStatus.FILLED
        assert trades[0].fill_price == 0.55

    @pytest.mark.asyncio
    async def test_filter_by_wallet(self, store):
        await store.save_trade(_make_trade(source_wallet="0xaaa"))
        await store.save_trade(_make_trade(source_wallet="0xbbb"))
        await store.save_trade(_make_trade(source_wallet="0xaaa"))

        trades = await store.get_trades_by_wallet("0xaaa")
        assert len(trades) == 2

    @pytest.mark.asyncio
    async def test_stats(self, store):
        await store.save_trade(_make_trade(pnl=10.0))
        await store.save_trade(_make_trade(pnl=-5.0))
        await store.save_trade(_make_trade(status=TradeStatus.FAILED, pnl=None))

        stats = await store.get_stats()
        assert stats["total"] == 3
        assert stats["filled"] == 2
        assert stats["failed"] == 1
        assert stats["total_pnl"] == 5.0
