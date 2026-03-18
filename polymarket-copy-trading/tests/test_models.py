"""Tests for data models."""

from __future__ import annotations

from datetime import datetime, timezone

from src.models import (
    CopiedTrade,
    CopySignal,
    PortfolioSnapshot,
    Position,
    SourceTrade,
    TradeStatus,
    TradeSide,
)


class TestSourceTrade:
    def test_create(self, sample_source_trade):
        assert sample_source_trade.side == TradeSide.BUY
        assert sample_source_trade.price == 0.65
        assert sample_source_trade.size == 50.0

    def test_fields(self):
        t = SourceTrade(
            trade_id="t1",
            wallet="0xabc",
            market_id="m1",
            asset_id="a1",
            side=TradeSide.SELL,
            price=0.35,
            size=10.0,
        )
        assert t.side == TradeSide.SELL
        assert t.market_question == ""


class TestPosition:
    def test_notional(self):
        p = Position(
            market_id="m1",
            asset_id="a1",
            side=TradeSide.BUY,
            size=100.0,
            avg_price=0.5,
        )
        assert p.notional == 50.0

    def test_zero_notional(self):
        p = Position(market_id="m1", asset_id="a1", side=TradeSide.BUY)
        assert p.notional == 0.0


class TestCopiedTrade:
    def test_defaults(self):
        t = CopiedTrade(
            source_trade_id="st1",
            source_wallet="0x123",
            market_id="m1",
            asset_id="a1",
            side=TradeSide.BUY,
            price=0.5,
            size=10.0,
        )
        assert t.status == TradeStatus.PENDING
        assert t.pnl is None


class TestPortfolioSnapshot:
    def test_defaults(self):
        snap = PortfolioSnapshot()
        assert snap.open_positions == 0
        assert snap.daily_pnl_usdc == 0.0
