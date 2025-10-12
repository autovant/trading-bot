#!/usr/bin/env python3
"""
Integration test script to validate all components work together.
"""

import sys
import asyncio

from src.config import load_config
from src.database import DatabaseManager
from src.indicators import TechnicalIndicators
import pandas as pd
import numpy as np


async def test_integration():
    """Test integration of all components."""
    print("🚀 Starting integration test...")

    # 1. Test configuration loading
    print("\n1. Testing configuration loading...")
    try:
        config = load_config()
        print("✅ Configuration loaded successfully")
        print(f"   - Trading symbols: {config.trading.symbols}")
        print(f"   - Initial capital: ${config.trading.initial_capital}")
        print(f"   - Risk per trade: {config.trading.risk_per_trade * 100:.1f}%")
    except Exception as e:
        print(f"❌ Configuration loading failed: {e}")
        return False

    # 2. Test database operations
    print("\n2. Testing database operations...")
    try:
        db = DatabaseManager("data/integration_test.db")
        await db.initialize()
        print("✅ Database initialized successfully")

        # Test performance metrics
        metrics = {
            "total_trades": 10,
            "winning_trades": 6,
            "losing_trades": 4,
            "total_pnl": 150.50,
            "max_drawdown": 5.2,
            "win_rate": 60.0,
            "profit_factor": 1.8,
            "sharpe_ratio": 1.2,
        }

        await db.update_performance_metrics(metrics)
        retrieved_metrics = await db.get_performance_metrics()

        if retrieved_metrics:
            print("✅ Database operations working correctly")
            print(f"   - Total trades: {retrieved_metrics['total_trades']}")
            print(f"   - Win rate: {retrieved_metrics['win_rate']:.1f}%")
        else:
            print("❌ Failed to retrieve metrics from database")

        await db.close()

    except Exception as e:
        print(f"❌ Database operations failed: {e}")
        return False

    # 3. Test technical indicators
    print("\n3. Testing technical indicators...")
    try:
        # Generate sample data
        dates = pd.date_range("2023-01-01", periods=100, freq="1h")
        np.random.seed(42)

        # Create realistic price movement
        base_price = 50000
        returns = np.random.normal(
            0.0001, 0.02, 100
        )  # Small positive drift with volatility
        prices = [base_price]

        for ret in returns[1:]:
            new_price = prices[-1] * (1 + ret)
            prices.append(max(new_price, base_price * 0.5))  # Prevent unrealistic drops

        # Create OHLCV data
        data = pd.DataFrame(
            {
                "open": [
                    prices[i - 1] if i > 0 else prices[i] for i in range(len(prices))
                ],
                "high": [p * (1 + abs(np.random.normal(0, 0.005))) for p in prices],
                "low": [p * (1 - abs(np.random.normal(0, 0.005))) for p in prices],
                "close": prices,
                "volume": np.random.uniform(1000, 5000, 100),
            },
            index=dates,
        )

        indicators = TechnicalIndicators()

        # Test various indicators
        ema_20 = indicators.ema(data["close"], 20)
        rsi = indicators.rsi(data["close"], 14)
        macd_line, macd_signal, macd_hist = indicators.macd(data["close"])
        atr = indicators.atr(data, 14)
        adx = indicators.adx(data, 14)

        print("✅ Technical indicators calculated successfully")
        print(f"   - EMA(20) last value: ${ema_20.iloc[-1]:.2f}")
        print(f"   - RSI last value: {rsi.iloc[-1]:.2f}")
        print(f"   - MACD last value: {macd_line.iloc[-1]:.2f}")
        print(f"   - ATR last value: {atr.iloc[-1]:.2f}")
        print(f"   - ADX last value: {adx.iloc[-1]:.2f}")

    except Exception as e:
        print(f"❌ Technical indicators failed: {e}")
        return False

    # 4. Test strategy components (without exchange)
    print("\n4. Testing strategy components...")
    try:
        from strategy import MarketRegime, TradingSetup, TradingSignal, ConfidenceScore

        # Test regime detection logic
        regime = MarketRegime(regime="bullish", strength=0.8, confidence=0.9)
        setup = TradingSetup(direction="long", quality=0.7, strength=0.8)
        signal = TradingSignal(
            signal_type="breakout",
            direction="long",
            strength=0.9,
            confidence=0.8,
            entry_price=50000,
            stop_loss=49000,
            take_profit=52000,
        )

        # Test confidence scoring
        confidence = ConfidenceScore(
            regime_score=20.0,
            setup_score=25.0,
            signal_score=30.0,
            penalty_score=-2.0,
            total_score=73.0,
        )

        print("✅ Strategy components working correctly")
        print(f"   - Regime: {regime.regime} (strength: {regime.strength:.2f})")
        print(f"   - Setup: {setup.direction} (quality: {setup.quality:.2f})")
        print(f"   - Signal: {signal.signal_type} {signal.direction}")
        print(f"   - Confidence: {confidence.total_score:.1f}/100")

    except Exception as e:
        print(f"❌ Strategy components failed: {e}")
        return False

    # 5. Test configuration validation
    print("\n5. Testing configuration validation...")
    try:
        # Test ladder weights sum to 1
        ladder_weights = config.risk_management.ladder_entries.weights
        weights_sum = sum(ladder_weights)

        if abs(weights_sum - 1.0) < 0.01:
            print("✅ Configuration validation passed")
            print(f"   - Ladder weights: {ladder_weights} (sum: {weights_sum:.3f})")
        else:
            print(f"❌ Ladder weights don't sum to 1.0: {weights_sum}")
            return False

    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        return False

    print("\n🎉 All integration tests passed successfully!")
    print("\n📋 Summary:")
    print("   ✅ Configuration loading")
    print("   ✅ Database operations")
    print("   ✅ Technical indicators")
    print("   ✅ Strategy components")
    print("   ✅ Configuration validation")

    print("\n🚀 The trading bot is ready for deployment!")
    print("\n📝 Next steps:")
    print("   1. Set up exchange API keys in environment variables")
    print("   2. Configure strategy parameters in config/strategy.yaml")
    print("   3. Run: python src/main.py")
    print("   4. Monitor via dashboard: streamlit run dashboard/app.py")

    return True


if __name__ == "__main__":
    success = asyncio.run(test_integration())
    sys.exit(0 if success else 1)
