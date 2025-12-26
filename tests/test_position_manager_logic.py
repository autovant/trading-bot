import pytest
from unittest.mock import MagicMock
from src.position_manager import PositionManager
from src.config import TradingBotConfig

@pytest.fixture
def position_manager():
    return PositionManager()

@pytest.fixture
def mock_config():
    config = MagicMock(spec=TradingBotConfig)
    config.trading = MagicMock()
    config.trading.risk_per_trade = 0.01 # 1% risk per trade logic proxy
    return config

def test_check_rebalance_needed_no_actions(position_manager, mock_config):
    # 10k balance, 20% cap = 2k.
    # Position: 1k value. OK.
    
    pos = MagicMock()
    pos.size = 1.0
    pos.mark_price = 1000.0
    pos.symbol = "BTC/USDT"
    
    actions = position_manager.check_rebalance_needed(
        positions=[pos],
        account_balance=10000.0,
        config=mock_config
    )
    assert len(actions) == 0

def test_check_rebalance_needed_trim_action(position_manager, mock_config):
    # 10k balance, 20% cap = 2000.
    # Position: 3000 value. Needs trim of 1000 value.
    
    pos = MagicMock()
    pos.size = 1.0
    pos.mark_price = 3000.0
    pos.symbol = "BTC/USDT"
    
    actions = position_manager.check_rebalance_needed(
        positions=[pos],
        account_balance=10000.0,
        config=mock_config
    )
    
    assert len(actions) == 1
    action = actions[0]
    assert action["symbol"] == "BTC/USDT"
    assert action["action"] == "reduce"
    
    # Excess value = 3000 - 2000 = 1000.
    # Price = 3000.
    # Qty to trim = 1000 / 3000 = 0.3333...
    assert action["quantity"] == pytest.approx(0.3333, rel=1e-3)
