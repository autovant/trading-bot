
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from src.engine.execution import ExecutionEngine
from src.config import TradingBotConfig, PerpsConfig, ExchangeConfig
from src.database import DatabaseManager

class MockExchange:
    def __init__(self, start_offset=0):
        self._time_offset_ms = start_offset
        self.__class__.__name__ = "MockExchange"

    @property
    def time_offset_ms(self):
        return self._time_offset_ms

    async def place_order(self, **kwargs):
        return {"order_id": "123"}

class MockLiveExchange(MockExchange):
    def __init__(self):
        super().__init__()
        self.__class__.__name__ = "LiveExchange"

class MockPaperExchange(MockExchange):
    def __init__(self):
        super().__init__()
        self.__class__.__name__ = "PaperExchange"

class MockSlowExchange(MockExchange):
    async def place_order(self, **kwargs):
        await asyncio.sleep(2) # longer than timeout
        return {"order_id": "123"}

@pytest.fixture
def config():
    c = TradingBotConfig(
        config_paths={
            "strategy": "config/strategy.yaml",
            "risk": "config/risk.yaml",
            "venues": "config/venues.yaml"
        },
        perps=PerpsConfig(timeSyncMaxSkewMs=100, orderAckTimeoutSeconds=1),
        app_mode="paper"
    )
    return c

@pytest.mark.asyncio
async def test_clock_drift_blocks_order(config):
    exchange = MockExchange(start_offset=200) # > 100 limit
    db = MagicMock(spec=DatabaseManager)
    
    engine = ExecutionEngine(
        config=config,
        exchange=exchange,
        database=db,
        messaging=None,
        position_manager=None,
        risk_manager=None,
        run_id="test",
        mode="paper"
    )
    
    # Needs intent first
    intent = MagicMock(client_id="cid", status="created")
    engine._ensure_intent = AsyncMock(return_value=intent)
    
    res = await engine.place_order_directly(
        symbol="BTC", side="buy", order_type="limit", quantity=1.0, idempotency_key="key"
    )
    assert res is None # Blocked

@pytest.mark.asyncio
async def test_order_ack_timeout(config):
    exchange = MockSlowExchange()
    db = MagicMock(spec=DatabaseManager)
    engine = ExecutionEngine(
        config=config,
        exchange=exchange,
        database=db,
        messaging=None,
        position_manager=None,
        risk_manager=None,
        run_id="test",
        mode="paper"
    )
    intent = MagicMock(client_id="cid", status="created", idempotency_key="key")
    engine._ensure_intent = AsyncMock(return_value=intent)
    
    res = await engine.place_order_directly(
         symbol="BTC", side="buy", order_type="limit", quantity=1.0, idempotency_key="key"
    )
    assert res is None # Should return None on timeout (handled internally)

@pytest.mark.asyncio
async def test_mode_mismatch_blocks(config):
    exchange = MockLiveExchange()
    db = MagicMock(spec=DatabaseManager)
    engine = ExecutionEngine(
        config=config,
        exchange=exchange,
        database=db,
        messaging=None,
        position_manager=None,
        risk_manager=None,
        run_id="test",
        mode="paper" # Mismatch with LiveExchange
    )
    
    intent = MagicMock(client_id="cid", status="created")
    engine._ensure_intent = AsyncMock(return_value=intent)
    
    res = await engine.place_order_directly(symbol="BTC", side="buy", order_type="limit", quantity=1.0, idempotency_key="k")
    assert res is None # Blocked

