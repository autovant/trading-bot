import pytest

from src.config import get_config
from src.risk_manager import RiskManager


@pytest.fixture
def config():
    return get_config()


@pytest.fixture
def risk_manager(config):
    return RiskManager(config)


@pytest.mark.asyncio
async def test_risk_manager_initialization(risk_manager):
    assert risk_manager.crisis_mode is False
    assert risk_manager.daily_pnl == 0.0
    assert risk_manager.peak_equity == 0.0


@pytest.mark.asyncio
async def test_update_trade_stats(risk_manager):
    risk_manager.update_trade_stats(100.0)
    assert risk_manager.daily_pnl == 100.0
    assert risk_manager.winning_trades == 1
    assert risk_manager.consecutive_losses == 0

    risk_manager.update_trade_stats(-50.0)
    assert risk_manager.daily_pnl == 50.0
    assert risk_manager.losing_trades == 1
    assert risk_manager.consecutive_losses == 1


@pytest.mark.asyncio
async def test_check_risk_management_drawdown(risk_manager):
    # Setup: Peak equity 1000
    risk_manager.peak_equity = 1000.0

    # 20% drawdown (threshold is usually 15% or similar in config, let's assume default config trigger)
    # If config default is 0.15 (15%), then 800 current equity is 20% DD.
    current_equity = 800.0

    actions = await risk_manager.check_risk_management(current_equity=current_equity)

    assert risk_manager.crisis_mode is True
    assert actions["halt_trading"] is True
    assert actions["close_all"] is True


@pytest.mark.asyncio
async def test_check_risk_management_daily_limit(risk_manager):
    # Max daily risk 0.03 (3%) usually.
    # Equity 1000. Limit = 30.
    risk_manager.daily_pnl = -60.0

    actions = await risk_manager.check_risk_management(current_equity=1000.0)

    assert actions["close_all"] is True
    assert actions["halt_trading"] is True

