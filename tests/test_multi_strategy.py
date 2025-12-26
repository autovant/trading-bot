from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.dynamic_strategy import (
    ConditionConfig,
    RegimeConfig,
    RiskConfig,
    SetupConfig,
    SignalConfig,
    StrategyConfig,
)
from src.strategy import TradingStrategy


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.app_mode = "paper"
    config.trading.symbols = ["BTC/USDT"]
    config.data.timeframes = {"regime": "1d", "setup": "4h", "signal": "1h"}
    config.data.lookback_periods = {"regime": 100, "setup": 100, "signal": 100}
    config.strategy.vwap.enabled = False
    config.strategy.orderbook.enabled = False
    config.strategy.confidence.min_threshold = 50
    return config


@pytest.fixture
def strategy_configs():
    # Strategy 1: Always Long
    strat1 = StrategyConfig(
        name="Strategy A",
        regime=RegimeConfig(),
        setup=SetupConfig(),
        signals=[
            SignalConfig(
                signal_type="test_long",
                direction="long",
                entry_conditions=[],  # Always true if empty? No, need a condition.
            )
        ],
        risk=RiskConfig(),
    )
    # Hack to make it always signal: use a condition that is always true
    strat1.signals[0].entry_conditions = [
        ConditionConfig(indicator_a=1, operator="==", indicator_b=1)
    ]
    strat1.confidence_threshold = 40.0

    # Strategy 2: Always Short
    strat2 = StrategyConfig(
        name="Strategy B",
        regime=RegimeConfig(),
        setup=SetupConfig(),
        signals=[
            SignalConfig(
                signal_type="test_short",
                direction="short",
                entry_conditions=[
                    ConditionConfig(indicator_a=1, operator="==", indicator_b=1)
                ],
            )
        ],
        risk=RiskConfig(),
    )
    strat2.confidence_threshold = 40.0
    return [strat1, strat2]


@pytest.mark.asyncio
async def test_multi_strategy_execution(mock_config, strategy_configs):
    exchange = MagicMock()
    database = AsyncMock()
    messaging = AsyncMock()

    # Initialize TradingStrategy with multiple configs
    strategy = TradingStrategy(
        config=mock_config,
        exchange=exchange,
        database=database,
        messaging=messaging,
        strategy_configs=strategy_configs,
    )

    assert len(strategy.dynamic_engines) == 2
    assert "Strategy A" in strategy.dynamic_engines
    assert "Strategy B" in strategy.dynamic_engines

    # Mock data
    dates = pd.date_range(start="2023-01-01", periods=100, freq="1h")
    df = pd.DataFrame(
        {
            "open": [100.0] * 100,
            "high": [105.0] * 100,
            "low": [95.0] * 100,
            "close": [100.0] * 100,
            "volume": [1000.0] * 100,
        },
        index=dates,
    )

    strategy.market_data = {"BTC/USDT": {"regime": df, "setup": df, "signal": df}}

    # Mock _execute_signal to capture calls
    strategy._execute_signal = AsyncMock()

    # Run analysis
    await strategy._analyze_symbol("BTC/USDT")

    # Verify both strategies triggered signals
    assert strategy._execute_signal.call_count >= 2

    # Check args of calls
    calls = strategy._execute_signal.call_args_list
    sources = [call.args[1].source for call in calls]
    directions = [call.args[1].direction for call in calls]

    assert "Strategy A" in sources
    assert "Strategy B" in sources
    assert "long" in directions
    assert "short" in directions
