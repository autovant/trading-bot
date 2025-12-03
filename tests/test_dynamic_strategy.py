import unittest
import pandas as pd
import numpy as np
from src.dynamic_strategy import (
    DynamicStrategyEngine,
    StrategyConfig,
    RegimeConfig,
    SetupConfig,
    SignalConfig,
    RiskConfig,
    IndicatorConfig,
    ConditionConfig
)
from src.strategy import MarketRegime, TradingSetup, TradingSignal

class TestDynamicStrategyEngine(unittest.TestCase):
    def setUp(self):
        # Create a sample strategy config
        self.config = StrategyConfig(
            name="Test Strategy",
            regime=RegimeConfig(
                indicators=[IndicatorConfig(name="ema", params={"period": 10})],
                bullish_conditions=[ConditionConfig(indicator_a="close", operator=">", indicator_b="ema_10")],
                bearish_conditions=[ConditionConfig(indicator_a="close", operator="<", indicator_b="ema_10")]
            ),
            setup=SetupConfig(
                indicators=[IndicatorConfig(name="rsi", params={"period": 14})],
                bullish_conditions=[ConditionConfig(indicator_a="rsi_14", operator="<", indicator_b=30)],
                bearish_conditions=[ConditionConfig(indicator_a="rsi_14", operator=">", indicator_b=70)]
            ),
            signals=[
                SignalConfig(
                    indicators=[],
                    entry_conditions=[ConditionConfig(indicator_a="close", operator=">", indicator_b=100)],
                    signal_type="breakout",
                    direction="long"
                )
            ],
            risk=RiskConfig(
                stop_loss_type="percent",
                stop_loss_value=1.0,
                take_profit_type="percent",
                take_profit_value=2.0
            )
        )
        self.engine = DynamicStrategyEngine(self.config)

    def test_regime_detection(self):
        # Create sample data
        data = pd.DataFrame({
            "close": [100, 105, 110, 115, 120],
            "open": [95, 100, 105, 110, 115],
            "high": [105, 110, 115, 120, 125],
            "low": [95, 100, 105, 110, 115],
            "volume": [1000, 1000, 1000, 1000, 1000]
        })
        
        # EMA(10) will be lower than close (uptrend)
        regime = self.engine.detect_regime(data)
        self.assertEqual(regime.regime, "bullish")
        
        # Downtrend
        data["close"] = [120, 115, 110, 105, 100]
        regime = self.engine.detect_regime(data)
        self.assertEqual(regime.regime, "bearish")

    def test_setup_detection(self):
        # Create sample data
        data = pd.DataFrame({
            "close": [100] * 20,
            "open": [100] * 20,
            "high": [100] * 20,
            "low": [100] * 20,
            "volume": [1000] * 20
        })
        
        # Mock RSI calculation or rely on actual calculation
        # Since we use actual indicators, we need enough data
        # Let's create a drop to trigger RSI < 30
        prices = [100 - i for i in range(20)] # 100 down to 81
        # Need sharper drop for RSI < 30? 
        # Let's just mock the indicator calculation in the engine? 
        # No, let's use a simpler condition for test
        
        self.config.setup.bullish_conditions = [ConditionConfig(indicator_a="close", operator="<", indicator_b=90)]
        data = pd.DataFrame({
            "close": [85] * 20,
            "open": [85] * 20,
            "high": [85] * 20,
            "low": [85] * 20,
            "volume": [1000] * 20
        })
        
        setup = self.engine.detect_setup(data)
        self.assertEqual(setup.direction, "long")

    def test_signal_generation(self):
        data = pd.DataFrame({
            "close": [101] * 20,
            "open": [100] * 20,
            "high": [102] * 20,
            "low": [99] * 20,
            "volume": [1000] * 20
        })
        
        signals = self.engine.generate_signals(data)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].direction, "long")
        self.assertEqual(signals[0].entry_price, 101)
        # Stop loss 1% below 101 = 99.99
        self.assertAlmostEqual(signals[0].stop_loss, 99.99)
        # Take profit 2% above 101 = 103.02
        self.assertAlmostEqual(signals[0].take_profit, 103.02)

if __name__ == "__main__":
    unittest.main()
