"""
Unit tests for trading strategy components.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.config import get_config
from src.indicators import TechnicalIndicators
from src.models import (
    ConfidenceScore,
    MarketRegime,
    OrderResponse,
    TradingSetup,
    TradingSignal,
)
from src.strategy import TradingStrategy


class MockExchange:
    """Mock exchange for testing."""

    async def get_historical_data(self, symbol, timeframe, limit):
        # Generate mock OHLCV data
        dates = pd.date_range(start="2023-01-01", periods=limit, freq="1H")
        np.random.seed(42)  # For reproducible tests

        # Generate realistic price data
        base_price = 50000 if symbol == "BTCUSDT" else 3000
        price_changes = np.random.normal(0, 0.01, limit)
        prices = [base_price]

        for change in price_changes[1:]:
            new_price = prices[-1] * (1 + change)
            prices.append(max(new_price, base_price * 0.5))  # Prevent negative prices

        # Create OHLCV data
        data = []
        for i, price in enumerate(prices):
            high = price * (1 + abs(np.random.normal(0, 0.005)))
            low = price * (1 - abs(np.random.normal(0, 0.005)))
            volume = np.random.uniform(1000, 10000)

            data.append(
                {
                    "open": prices[i - 1] if i > 0 else price,
                    "high": high,
                    "low": low,
                    "close": price,
                    "volume": volume,
                }
            )

        df = pd.DataFrame(data, index=dates)
        return df

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

    async def get_balance(self):
        return {"totalWalletBalance": 1000.0}

    async def get_market_status(self):
        return {"status": "ok"}

    async def get_ticker(self, symbol):
        return {"last": 50000.0}

    async def get_order_book(self, symbol, limit=20):
        return {"bids": [], "asks": []}

    async def cancel_all_orders(self, symbol):
        return []

    async def initialize(self):
        pass

    async def close(self):
        pass


class MockDatabase:
    """Mock database for testing."""

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
    """Load test configuration."""
    return get_config()


@pytest.fixture
def mock_exchange():
    """Create mock exchange."""
    return MockExchange()


@pytest.fixture
def mock_database():
    """Create mock database."""
    return MockDatabase()


@pytest.fixture
def strategy(config, mock_exchange, mock_database):
    """Create strategy instance for testing."""
    return TradingStrategy(
        config,
        mock_exchange,
        mock_database,
        messaging=None,
        paper_broker=None,
        run_id="test-run",
    )


@pytest.fixture
def sample_data():
    """Generate sample market data for testing."""
    dates = pd.date_range(start="2023-01-01", periods=200, freq="h")
    np.random.seed(42)

    # Generate trending price data
    base_price = 50000
    trend = np.linspace(0, 0.1, 200)  # 10% uptrend
    noise = np.random.normal(0, 0.02, 200)

    prices = base_price * (1 + trend + noise)

    data = []
    for i, price in enumerate(prices):
        high = price * 1.01
        low = price * 0.99
        volume = np.random.uniform(1000, 5000)

        data.append(
            {
                "open": prices[i - 1] if i > 0 else price,
                "high": high,
                "low": low,
                "close": price,
                "volume": volume,
            }
        )

    return pd.DataFrame(data, index=dates)


class TestTechnicalIndicators:
    """Test technical indicators."""

    def test_ema_calculation(self, sample_data):
        """Test EMA calculation."""
        indicators = TechnicalIndicators()
        ema = indicators.ema(sample_data["close"], 20)

        assert len(ema) == len(sample_data)
        assert not ema.isna().all()
        assert ema.iloc[-1] > 0

    def test_rsi_calculation(self, sample_data):
        """Test RSI calculation."""
        indicators = TechnicalIndicators()
        rsi = indicators.rsi(sample_data["close"], 14)

        assert len(rsi) == len(sample_data)
        assert rsi.max() <= 100
        assert rsi.min() >= 0

    def test_macd_calculation(self, sample_data):
        """Test MACD calculation."""
        indicators = TechnicalIndicators()
        macd_line, signal_line, histogram = indicators.macd(sample_data["close"])

        assert len(macd_line) == len(sample_data)
        assert len(signal_line) == len(sample_data)
        assert len(histogram) == len(sample_data)

    def test_atr_calculation(self, sample_data):
        """Test ATR calculation."""
        indicators = TechnicalIndicators()
        atr = indicators.atr(sample_data, 14)

        assert len(atr) == len(sample_data)
        assert (atr.dropna() >= 0).all()

    def test_adx_calculation(self, sample_data):
        """Test ADX calculation."""
        indicators = TechnicalIndicators()
        adx = indicators.adx(sample_data, 14)

        assert len(adx) == len(sample_data)
        assert (adx.dropna() >= 0).all()
        assert (adx.dropna() <= 100).all()


class TestRegimeDetection:
    """Test regime detection logic."""

    def test_bullish_regime_detection(self, strategy, sample_data):
        """Test bullish regime detection."""
        # Create bullish conditions
        bullish_data = sample_data.copy()
        bullish_data["close"] = bullish_data["close"] * np.linspace(
            1, 1.2, len(bullish_data)
        )

        regime = strategy.signal_generator.detect_regime(
            bullish_data, strategy.config.strategy
        )

        assert isinstance(regime, MarketRegime)
        assert regime.regime in ["bullish", "neutral"]
        assert 0 <= regime.strength <= 1
        assert 0 <= regime.confidence <= 1

    def test_bearish_regime_detection(self, strategy, sample_data):
        """Test bearish regime detection."""
        # Create bearish conditions
        bearish_data = sample_data.copy()
        bearish_data["close"] = bearish_data["close"] * np.linspace(
            1, 0.8, len(bearish_data)
        )

        regime = strategy.signal_generator.detect_regime(
            bearish_data, strategy.config.strategy
        )

        assert isinstance(regime, MarketRegime)
        assert regime.regime in ["bearish", "neutral"]
        assert 0 <= regime.strength <= 1
        assert 0 <= regime.confidence <= 1


class TestSetupDetection:
    """Test setup detection logic."""

    def test_bullish_setup_detection(self, strategy, sample_data):
        """Test bullish setup detection."""
        setup = strategy.signal_generator.detect_setup(
            sample_data, strategy.config.strategy
        )

        assert isinstance(setup, TradingSetup)
        assert setup.direction in ["long", "short", "none"]
        assert 0 <= setup.quality <= 1
        assert 0 <= setup.strength <= 1

    def test_setup_with_insufficient_data(self, strategy):
        """Test setup detection with insufficient data."""
        short_data = pd.DataFrame(
            {
                "open": [100, 101],
                "high": [102, 103],
                "low": [99, 100],
                "close": [101, 102],
                "volume": [1000, 1100],
            }
        )

        setup = strategy.signal_generator.detect_setup(
            short_data, strategy.config.strategy
        )

        assert isinstance(setup, TradingSetup)
        assert setup.direction == "none"


class TestSignalGeneration:
    """Test signal generation logic."""

    def test_signal_generation(self, strategy, sample_data):
        """Test signal generation."""
        signals = strategy.signal_generator.generate_signals(
            sample_data, strategy.config.strategy
        )

        assert isinstance(signals, list)

        for signal in signals:
            assert isinstance(signal, TradingSignal)
            assert signal.signal_type in ["pullback", "breakout", "divergence"]
            assert signal.direction in ["long", "short"]
            assert 0 <= signal.strength <= 1
            assert 0 <= signal.confidence <= 1
            assert signal.entry_price > 0
            assert signal.stop_loss > 0
            assert signal.take_profit > 0


class TestConfidenceScoring:
    """Test confidence scoring system."""

    def test_confidence_calculation(self, strategy):
        """Test confidence score calculation."""
        # Create test components
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

        confidence = strategy.position_manager.calculate_confidence(
            regime, setup, signal, strategy.config.strategy, symbol="BTCUSDT"
        )

        assert isinstance(confidence, ConfidenceScore)
        assert 0 <= confidence.total_score <= 100
        assert confidence.regime_score >= 0
        assert confidence.setup_score >= 0
        assert confidence.signal_score >= 0

    def test_confidence_with_penalties(self, strategy):
        """Test confidence calculation with penalties."""
        regime = MarketRegime(regime="bullish", strength=0.8, confidence=0.9)
        setup = TradingSetup(
            direction="short", quality=0.7, strength=0.8
        )  # Conflicting
        signal = TradingSignal(
            signal_type="breakout",
            direction="long",
            strength=0.9,
            confidence=0.8,
            entry_price=50000,
            stop_loss=49000,
            take_profit=52000,
        )

        confidence = strategy.position_manager.calculate_confidence(
            regime, setup, signal, strategy.config.strategy, symbol="BTCUSDT"
        )

        # Should have penalty for conflicting timeframes
        assert confidence.penalty_score < 0


class TestPositionSizing:
    """Test position sizing logic."""

    def test_position_size_calculation(self, strategy):
        """Test position size calculation."""
        signal = TradingSignal(
            signal_type="breakout",
            direction="long",
            strength=0.9,
            confidence=0.8,
            entry_price=50000,
            stop_loss=49000,
            take_profit=52000,
        )

        confidence = ConfidenceScore(
            regime_score=20,
            setup_score=25,
            signal_score=30,
            penalty_score=0,
            total_score=75,
        )

        position_size = strategy.position_manager.calculate_position_size(
            signal,
            confidence,
            strategy.config.trading.initial_capital,  # account_balance
            strategy.config.trading.initial_capital,  # initial_capital
            strategy.config,  # bot config
            strategy.crisis_mode,
        )

        assert position_size > 0
        assert isinstance(position_size, float)

    def test_position_size_with_crisis_mode(self, strategy):
        """Test position sizing in crisis mode."""
        strategy.risk_manager.crisis_mode = True

        signal = TradingSignal(
            signal_type="breakout",
            direction="long",
            strength=0.9,
            confidence=0.8,
            entry_price=50000,
            stop_loss=49000,
            take_profit=52000,
        )

        confidence = ConfidenceScore(
            regime_score=20,
            setup_score=25,
            signal_score=30,
            penalty_score=0,
            total_score=75,
        )

        crisis_size = strategy.position_manager.calculate_position_size(
            signal,
            confidence,
            strategy.config.trading.initial_capital,
            strategy.config.trading.initial_capital,
            strategy.config,
            strategy.risk_manager.crisis_mode,
        )

        strategy.risk_manager.crisis_mode = False
        normal_size = strategy.position_manager.calculate_position_size(
            signal,
            confidence,
            strategy.config.trading.initial_capital,
            strategy.config.trading.initial_capital,
            strategy.config,
            strategy.risk_manager.crisis_mode,
        )

        assert crisis_size < normal_size


class TestRiskManagement:
    """Test risk management features."""

    @pytest.mark.asyncio
    async def test_crisis_mode_activation(self, strategy):
        """Test crisis mode activation."""
        strategy.risk_manager.consecutive_losses = 3
        strategy.total_pnl = (
            -100
        )  # Strategy still tracks total_pnl? Yes, updated in handle_exec
        # But check_risk_management uses account_balance = initial + total_pnl
        # And checks peak_equity inside RiskManager.
        # RiskManager tracks its OWN peak_equity.
        # So we need to ensure RiskManager knows about the pnl state or peak equity.
        # check_risk_management passes current_equity (1000 - 100 = 900).
        # RiskManager peak_equity starts at 0.
        # If current_equity > peak_equity, it updates.
        # So 900 > 0.
        # DD = 0.
        # So NO crisis mode if peak_equity isn't set high enough.

        # We need to prime RiskManager peak_equity.
        strategy.risk_manager.peak_equity = 1000.0

        # strategy.total_pnl is used to calc account_balance passed to RM.

        await strategy.check_risk_management()

        # Crisis mode should be activated
        assert strategy.risk_manager.crisis_mode

    def test_signal_filtering(self, strategy):
        """Test signal filtering based on regime and setup."""
        regime = MarketRegime(regime="bullish", strength=0.8, confidence=0.9)
        setup = TradingSetup(direction="long", quality=0.7, strength=0.8)
        signals = [
            TradingSignal(
                signal_type="breakout",
                direction="long",
                strength=0.8,
                confidence=0.7,
                entry_price=50000,
                stop_loss=49000,
                take_profit=52000,
            ),
            TradingSignal(
                signal_type="pullback",
                direction="short",
                strength=0.7,
                confidence=0.6,
                entry_price=50000,
                stop_loss=51000,
                take_profit=48000,
            ),
        ]

        filtered = strategy.signal_generator.filter_signals(signals, regime, setup)

        # Should only keep the long signal
        assert len(filtered) == 1
        assert filtered[0].direction == "long"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
