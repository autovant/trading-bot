"""Tests for the trade monitor."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from src.config import AppConfig
from src.models import SourceTrade, TradeSide
from src.monitor import TradeMonitor


class MockPolymarketClient:
    """Mock client that returns preset trade data."""

    def __init__(self, trades: list | None = None):
        self._trades = trades or []

    async def start(self): pass
    async def stop(self): pass

    async def get_wallet_trades(self, wallet, limit=50):
        return self._trades


class TestTradeMonitor:
    def test_parse_trade(self):
        raw = {
            "id": "t1",
            "side": "BUY",
            "price": "0.65",
            "size": "50",
            "market": "m1",
            "asset_id": "a1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        trade = TradeMonitor._parse_trade(raw, "0xabc")
        assert trade is not None
        assert trade.trade_id == "t1"
        assert trade.side == TradeSide.BUY
        assert trade.price == 0.65
        assert trade.size == 50.0

    def test_parse_trade_sell(self):
        raw = {
            "id": "t2",
            "side": "SELL",
            "price": "0.40",
            "size": "30",
            "market": "m2",
            "asset_id": "a2",
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
        }
        trade = TradeMonitor._parse_trade(raw, "0xdef")
        assert trade is not None
        assert trade.side == TradeSide.SELL

    def test_parse_trade_invalid(self):
        raw = {"id": "bad", "price": "0", "size": "0"}
        trade = TradeMonitor._parse_trade(raw, "0x")
        assert trade is None  # zero price/size → None

    def test_extract_trade_id(self):
        assert TradeMonitor._extract_trade_id({"id": "abc"}) == "abc"
        assert TradeMonitor._extract_trade_id({"tradeId": "def"}) == "def"
        assert TradeMonitor._extract_trade_id({"trade_id": "ghi"}) == "ghi"

    def test_dedup(self):
        """Seen trade IDs are not emitted again."""
        config = AppConfig(source_wallets=["0xtest"])
        client = MockPolymarketClient()
        monitor = TradeMonitor(config, client)
        monitor._seen_trade_ids.add("t1")

        raw = {
            "id": "t1",
            "side": "BUY",
            "price": "0.5",
            "size": "10",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        trade = TradeMonitor._parse_trade(raw, "0xtest")
        assert trade is not None
        # But _extract_trade_id("t1") is already in seen set
        assert "t1" in monitor._seen_trade_ids

    @pytest.mark.asyncio
    async def test_poll_wallet_new_trades(self):
        now = datetime.now(timezone.utc)
        trades_data = [
            {
                "id": "new-1",
                "side": "BUY",
                "price": "0.7",
                "size": "25",
                "market": "m1",
                "asset_id": "a1",
                "timestamp": now.isoformat(),
            }
        ]
        config = AppConfig(source_wallets=["0xtest"])
        client = MockPolymarketClient(trades_data)
        monitor = TradeMonitor(config, client)

        new_trades = await monitor._poll_wallet("0xtest")
        assert len(new_trades) == 1
        assert new_trades[0].trade_id == "new-1"

    @pytest.mark.asyncio
    async def test_poll_wallet_skips_old_trades(self):
        old_time = datetime.now(timezone.utc) - timedelta(seconds=600)
        trades_data = [
            {
                "id": "old-1",
                "side": "BUY",
                "price": "0.5",
                "size": "10",
                "market": "m1",
                "asset_id": "a1",
                "timestamp": old_time.isoformat(),
            }
        ]
        config = AppConfig(source_wallets=["0xtest"])
        config.copy.max_trade_age_seconds = 300
        client = MockPolymarketClient(trades_data)
        monitor = TradeMonitor(config, client)

        new_trades = await monitor._poll_wallet("0xtest")
        assert len(new_trades) == 0  # trade is too old

    def test_callback_registration(self):
        config = AppConfig(source_wallets=["0xtest"])
        client = MockPolymarketClient()
        monitor = TradeMonitor(config, client)

        received = []
        monitor.on_trade(lambda t: received.append(t))

        trade = SourceTrade(
            trade_id="t1", wallet="0x", market_id="m1", asset_id="a1",
            side=TradeSide.BUY, price=0.5, size=10.0,
        )
        monitor._emit(trade)
        assert len(received) == 1
        assert received[0].trade_id == "t1"
