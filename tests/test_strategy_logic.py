import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.config import get_config
from src.models import MarketRegime, OrderResponse
from src.strategy import ConfidenceScore, TradingSignal, TradingStrategy


# --- Mocks (Copied from test_strategy.py to make this standalone) ---
class MockExchange:
    async def get_historical_data(self, symbol, timeframe, limit):
        return pd.DataFrame()  # Just return empty for logic tests, or mock if needed

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
        order_id = (
            client_id
            or f"mock-{symbol}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        )
        return OrderResponse(
            order_id=order_id,
            client_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status="pending",
            mode="paper",
            timestamp=datetime.now(timezone.utc),
        )

    async def get_positions(self, symbols=None):
        return []

    async def close_position(self, symbol: str) -> bool:
        return True

    async def get_account_balance(self):
        return {"totalWalletBalance": 1000.0}


class MockDatabase:
    def __init__(self):
        self.orders = []
        self.trades = []
        self.positions = []

    async def create_order(self, order):
        self.orders.append(order)
        return len(self.orders)

    async def create_trade(self, trade):
        self.trades.append(trade)
        return len(self.trades)

    async def update_position(self, position):
        self.positions.append(position)
        return True

    async def update_order_status(self, order_id, status, is_shadow=False):
        return True

    async def add_pnl_entry(self, entry):
        return True


@pytest.fixture
def config():
    return get_config()


@pytest.fixture
def mock_exchange():
    return MockExchange()


@pytest.fixture
def mock_database():
    return MockDatabase()


# --- Logic Tests ---


@pytest.mark.asyncio
async def test_pnl_accumulation_and_position_sizing(mock_exchange, mock_database):
    """Test that realized PnL updates total_pnl and affects position sizing."""
    config = get_config()
    strategy = TradingStrategy(config, mock_exchange, mock_database)

    # 1. Initial State
    assert strategy.total_pnl == 0.0
    initial_balance = config.trading.initial_capital

    # Mock confidence and signal
    confidence = ConfidenceScore(
        regime_score=25,
        setup_score=25,
        signal_score=35,
        penalty_score=0,
        total_score=85,
    )
    signal = TradingSignal(
        signal_type="breakout",
        direction="long",
        strength=1.0,
        confidence=1.0,
        entry_price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        timestamp=datetime.now(timezone.utc),
    )

    # Calculate size with 0 PnL
    size_0 = strategy._calculate_position_size(signal, confidence)
    expected_risk_0 = initial_balance * config.trading.risk_per_trade
    # risk = size * (entry - stop) -> size = risk / (entry - stop)
    expected_size_0 = expected_risk_0 / (100.0 - 90.0)
    assert abs(size_0 - expected_size_0) < 0.001

    # 2. Simulate profitable trade execution report
    profit = 1000.0
    report = {
        "executed": True,
        "order_id": "test-order-1",
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": 1.0,
        "price": 100.0,
        "realized_pnl": profit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Mock message
    msg = MagicMock()
    msg.data = json.dumps(report).encode("utf-8")

    # Process report
    await strategy._handle_execution_report(msg)

    # Verify PnL updated
    assert strategy.total_pnl == profit

    # 3. Calculate size with updated PnL
    size_1 = strategy._calculate_position_size(signal, confidence)
    new_balance = initial_balance + profit
    expected_risk_1 = new_balance * config.trading.risk_per_trade
    expected_size_1 = expected_risk_1 / (100.0 - 90.0)

    assert size_1 > size_0
    assert abs(size_1 - expected_size_1) < 0.001


@pytest.mark.asyncio
async def test_race_condition_protection(mock_exchange, mock_database):
    """Test that processing_orders set prevents double execution."""
    config = get_config()
    strategy = TradingStrategy(config, mock_exchange, mock_database)
    symbol = "BTCUSDT"

    # Mock necessary objects
    signal = TradingSignal(
        signal_type="breakout",
        direction="long",
        strength=1.0,
        confidence=1.0,
        entry_price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        timestamp=datetime.now(timezone.utc),
    )
    confidence = ConfidenceScore(
        regime_score=25,
        setup_score=25,
        signal_score=35,
        penalty_score=0,
        total_score=85,
    )
    regime = MarketRegime(regime="bullish", strength=1.0, confidence=1.0)

    # Mock internal methods to simulate delay
    strategy._calculate_position_size = MagicMock(return_value=1.0)
    strategy._generate_client_id = MagicMock(return_value="test-client-id")
    strategy._place_order_directly = AsyncMock(return_value=None)  # Just mocked

    # 1. Start execution
    # We can't easily simulate concurrency in a single-threaded test without complex setup,
    # but we can verify the logic by manually setting the processing flag.

    strategy.processing_orders.add(symbol)

    # Try to execute
    await strategy._execute_signal(symbol, signal, confidence, regime)

    # Verify NO order was placed because symbol was in processing_orders
    strategy._place_order_directly.assert_not_called()

    # 2. Clear flag and retry
    strategy.processing_orders.discard(symbol)
    await strategy._execute_signal(symbol, signal, confidence, regime)

    # Verify order WAS placed
    strategy._place_order_directly.assert_called_once()
