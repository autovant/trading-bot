import asyncio
import pytest
from datetime import datetime
from src.paper_trader import PaperBroker
from src.config import PaperConfig, RiskManagementConfig, LatencyConfig, PartialFillConfig
from src.database import DatabaseManager
from src.models import MarketSnapshot, Side, OrderType

# Helper to run async code
def run_async(coro):
    return asyncio.run(coro)

async def _setup_broker():
    manager = DatabaseManager(":memory:")
    await manager.initialize()
    
    paper_config = PaperConfig(
        fee_bps=10.0,
        maker_rebate_bps=2.0,
        slippage_bps=5.0,
        latency_ms=LatencyConfig(mean=10.0, p95=20.0),
        partial_fill=PartialFillConfig(enabled=True, min_slice_pct=0.1, max_slices=5)
    )
    
    broker = PaperBroker(
        config=paper_config,
        database=manager,
        mode="paper",
        run_id="test_run",
        initial_balance=10000.0
    )
    return broker, manager

async def _test_market_order_buy_impl():
    broker, manager = await _setup_broker()
    try:
        symbol = "BTCUSDT"
        snapshot = MarketSnapshot(
            symbol=symbol,
            best_bid=50000.0,
            best_ask=50010.0,
            bid_size=1.0,
            ask_size=1.0,
            last_price=50005.0,
            timestamp=datetime.utcnow()
        )
        
        # Update market first
        await broker.update_market(snapshot)
        
        # Place Buy Order
        order = await broker.place_order(
            symbol=symbol,
            side="buy",
            order_type="market",
            quantity=0.1
        )
        
        assert order.status == "open"
        
        # Wait for execution (simulated latency)
        await asyncio.sleep(0.1)
        
        # Check positions
        positions = await broker.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.symbol == symbol
        assert pos.side == "long"
        assert pos.size == 0.1
        # Entry price should include slippage
        assert pos.entry_price > 50010.0 
    finally:
        await manager.close()

def test_market_order_buy():
    run_async(_test_market_order_buy_impl())

async def _test_limit_order_fill_impl():
    broker, manager = await _setup_broker()
    try:
        symbol = "ETHUSDT"
        # Initial market
        snapshot = MarketSnapshot(
            symbol=symbol,
            best_bid=3000.0,
            best_ask=3010.0,
            bid_size=10.0,
            ask_size=10.0,
            last_price=3005.0,
            timestamp=datetime.utcnow()
        )
        await broker.update_market(snapshot)
        
        # Place Limit Buy below market
        order = await broker.place_order(
            symbol=symbol,
            side="buy",
            order_type="limit",
            quantity=1.0,
            price=2990.0
        )
        
        await asyncio.sleep(0.05)
        positions = await broker.get_positions()
        assert len(positions) == 0 # Should not be filled yet
        
        # Move market down to cross limit
        snapshot2 = MarketSnapshot(
            symbol=symbol,
            best_bid=2980.0,
            best_ask=2985.0, # Ask is now below limit price 2990
            bid_size=10.0,
            ask_size=10.0,
            last_price=2982.0,
            timestamp=datetime.utcnow()
        )
        await broker.update_market(snapshot2)
        
        await asyncio.sleep(0.1)
        
        positions = await broker.get_positions()
        assert len(positions) == 1
        # Limit price was 2990.0. Market moved to 2985.0.
        # We should get filled at 2990.0 or better (lower).
        assert positions[0].entry_price <= 2990.0
        # And reasonably close to market price 2985
        assert positions[0].entry_price >= 2980.0
    finally:
        await manager.close()

def test_limit_order_fill():
    run_async(_test_limit_order_fill_impl())

async def _test_pnl_calculation_impl():
    broker, manager = await _setup_broker()
    try:
        symbol = "SOLUSDT"
        snapshot = MarketSnapshot(
            symbol=symbol,
            best_bid=100.0,
            best_ask=100.1,
            bid_size=100.0,
            ask_size=100.0,
            last_price=100.05,
            timestamp=datetime.utcnow()
        )
        await broker.update_market(snapshot)
        
        # Buy 10 SOL
        await broker.place_order(symbol, "buy", "market", 10.0)
        await asyncio.sleep(0.1)
        
        # Price moves up 10%
        snapshot2 = MarketSnapshot(
            symbol=symbol,
            best_bid=110.0,
            best_ask=110.1,
            bid_size=100.0,
            ask_size=100.0,
            last_price=110.05,
            timestamp=datetime.utcnow()
        )
        await broker.update_market(snapshot2)
        
        positions = await broker.get_positions()
        pos = positions[0]
        # Unrealized PnL ~ (110.05 - Entry) * 10
        # Entry approx 100.1 + slippage
        expected_pnl = (110.05 - pos.entry_price) * 10.0
        assert abs(pos.unrealized_pnl - expected_pnl) < 0.01
        
        # Close position
        await broker.close_position(symbol)
        await asyncio.sleep(0.1)
        
        positions = await broker.get_positions()
        assert len(positions) == 0
        
        balance = await broker.get_account_balance()
        # Initial 10000 + Profit - Fees
        assert balance["totalWalletBalance"] > 10000.0
    finally:
        await manager.close()

def test_pnl_calculation():
    run_async(_test_pnl_calculation_impl())
