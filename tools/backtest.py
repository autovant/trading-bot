"""
Historical backtesting engine with realistic execution simulation.
"""

import asyncio
import argparse
import json
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import sys

from src.config import get_config, TradingBotConfig
from src.exchange import ExchangeClient
from src.strategy import MarketRegime, TradingSetup, TradingSignal
from src.indicators import TechnicalIndicators
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """Historical backtesting engine."""

    def __init__(self, config: TradingBotConfig):
        self.config = config
        self.indicators = TechnicalIndicators()

        # Backtest state
        self.initial_balance = config.backtesting.initial_balance
        self.current_balance = self.initial_balance
        self.positions: Dict[str, Dict] = {}
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []

        # Performance metrics
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.peak_equity = self.initial_balance

        # Execution parameters
        self.slippage = config.backtesting.slippage
        self.commission = config.backtesting.commission

    async def run_backtest(self, symbol: str, start_date: str, end_date: str) -> Dict:
        """Run backtest for a symbol over date range."""
        try:
            logger.info(
                f"Starting backtest for {symbol} from {start_date} to {end_date}"
            )

            # Initialize exchange client for data fetching
            exchange = ExchangeClient(
                self.config.exchange,
                app_mode="live",
            )
            await exchange.initialize()

            # Fetch historical data for all timeframes
            data = await self._fetch_historical_data(
                exchange, symbol, start_date, end_date
            )

            if not data:
                logger.error("Failed to fetch historical data")
                return {}

            # Run simulation
            await self._simulate_trading(symbol, data)

            # Calculate performance metrics
            performance = self._calculate_performance()

            # Close exchange
            await exchange.close()

            logger.info(
                f"Backtest completed. Total P&L: ${performance['total_pnl']:.2f}"
            )

            return performance

        except Exception as e:
            logger.error(f"Backtest error: {e}")
            return {}

    async def _fetch_historical_data(
        self, exchange: ExchangeClient, symbol: str, start_date: str, end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """Fetch historical data for all required timeframes."""
        data: Dict[str, pd.DataFrame] = {}

        try:
            # Calculate required periods
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            days_diff = (end_dt - start_dt).days

            # Fetch data for each timeframe
            for tf_name, timeframe in self.config.data.timeframes.items():
                logger.info(f"Fetching {timeframe} data for {symbol}...")

                # Calculate limit based on timeframe and date range
                if timeframe == "1h":
                    limit = min(days_diff * 24 + 200, 1000)
                elif timeframe == "4h":
                    limit = min(days_diff * 6 + 100, 1000)
                elif timeframe == "1d":
                    limit = min(days_diff + 50, 1000)
                else:
                    limit = 1000

                df = await exchange.get_historical_data(symbol, timeframe, limit)

                if df is not None and not df.empty:
                    # Filter by date range
                    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
                    data[tf_name] = df
                    logger.info(f"Loaded {len(df)} bars for {timeframe}")
                else:
                    logger.warning(f"No data for {timeframe}")

            return data

        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return {}

    async def _simulate_trading(self, symbol: str, data: Dict[str, pd.DataFrame]):
        """Simulate trading strategy on historical data."""
        try:
            signal_data = data.get("signal")  # 1h data for simulation

            if signal_data is None or signal_data.empty:
                logger.error("No signal data available")
                return

            logger.info(f"Simulating {len(signal_data)} periods...")

            # Simulate each time period
            for i in range(max(200, len(signal_data) // 10), len(signal_data)):
                current_time = signal_data.index[i]

                # Get data up to current time
                current_data: Dict[str, pd.DataFrame] = {
                    "regime": (
                        data["regime"].iloc[: i + 1]
                        if "regime" in data
                        else pd.DataFrame()
                    ),
                    "setup": (
                        data["setup"].iloc[: i + 1]
                        if "setup" in data
                        else pd.DataFrame()
                    ),
                    "signal": signal_data.iloc[: i + 1],
                }

                # Skip if insufficient data
                if any(d.empty or len(d) < 50 for d in current_data.values()):
                    continue

                # Analyze current market conditions
                await self._analyze_market(symbol, current_data, current_time)

                # Update positions
                self._update_positions(symbol, signal_data.iloc[i])

                # Record equity
                self._record_equity(current_time)

                # Progress logging
                if i % 100 == 0:
                    progress = (i / len(signal_data)) * 100
                    logger.info(
                        f"Progress: {progress:.1f}% - Balance: ${self.current_balance:.2f}"
                    )

        except Exception as e:
            logger.error(f"Error in trading simulation: {e}")

    async def _analyze_market(
        self, symbol: str, data: Dict[str, pd.DataFrame], current_time: datetime
    ):
        """Analyze market conditions and generate signals."""
        try:
            # 1. Regime Detection
            regime = self._detect_regime(data["regime"])

            # 2. Setup Detection
            setup = self._detect_setup(data["setup"])

            # 3. Signal Generation
            signals = self._generate_signals(data["signal"])

            # 4. Filter and score signals
            if regime and setup and signals:
                valid_signals = self._filter_signals(signals, regime, setup)

                for signal in valid_signals:
                    confidence = self._calculate_confidence(regime, setup, signal)

                    if confidence >= self.config.strategy.confidence.min_threshold:
                        await self._execute_signal(
                            symbol, signal, confidence, current_time
                        )

        except Exception as e:
            logger.error(f"Error analyzing market: {e}")

    def _detect_regime(self, data: pd.DataFrame) -> Optional[MarketRegime]:
        """Detect market regime (simplified version)."""
        try:
            if len(data) < self.config.strategy.regime.ema_period:
                return None

            # Calculate indicators
            ema_200 = self.indicators.ema(
                data["close"], self.config.strategy.regime.ema_period
            )
            macd_line, _, _ = self.indicators.macd(
                data["close"],
                self.config.strategy.regime.macd_fast,
                self.config.strategy.regime.macd_slow,
                self.config.strategy.regime.macd_signal,
            )

            # Current values
            current_price = data["close"].iloc[-1]
            current_ema = ema_200.iloc[-1]
            current_macd = macd_line.iloc[-1]

            # Determine regime
            if current_price > current_ema and current_macd > 0:
                regime = "bullish"
                strength = min(1.0, (current_price - current_ema) / current_ema * 10)
            elif current_price < current_ema and current_macd < 0:
                regime = "bearish"
                strength = min(1.0, (current_ema - current_price) / current_ema * 10)
            else:
                regime = "neutral"
                strength = 0.5

            confidence = strength * (
                1.0 if (current_price > current_ema) == (current_macd > 0) else 0.3
            )

            return MarketRegime(regime=regime, strength=strength, confidence=confidence)

        except Exception as e:
            logger.error(f"Error detecting regime: {e}")
            return None

    def _detect_setup(self, data: pd.DataFrame) -> Optional[TradingSetup]:
        """Detect trading setup (simplified version)."""
        try:
            if len(data) < max(
                self.config.strategy.setup.ema_slow,
                self.config.strategy.setup.adx_period,
            ):
                return None

            # Calculate EMAs and ADX
            ema_8 = self.indicators.ema(
                data["close"], self.config.strategy.setup.ema_fast
            )
            ema_21 = self.indicators.ema(
                data["close"], self.config.strategy.setup.ema_medium
            )
            ema_55 = self.indicators.ema(
                data["close"], self.config.strategy.setup.ema_slow
            )
            adx = self.indicators.adx(data, self.config.strategy.setup.adx_period)

            # Current values
            current_ema8 = ema_8.iloc[-1]
            current_ema21 = ema_21.iloc[-1]
            current_ema55 = ema_55.iloc[-1]
            current_adx = adx.iloc[-1]

            # Check setup conditions
            bullish_stack = current_ema8 > current_ema21 > current_ema55
            bearish_stack = current_ema8 < current_ema21 < current_ema55
            strong_trend = current_adx > self.config.strategy.setup.adx_threshold

            if bullish_stack and strong_trend:
                direction = "long"
                quality = min(1.0, current_adx / 50.0)
                strength = 0.8
            elif bearish_stack and strong_trend:
                direction = "short"
                quality = min(1.0, current_adx / 50.0)
                strength = 0.8
            else:
                direction = "none"
                quality = 0.0
                strength = 0.0

            return TradingSetup(direction=direction, quality=quality, strength=strength)

        except Exception as e:
            logger.error(f"Error detecting setup: {e}")
            return None

    def _generate_signals(self, data: pd.DataFrame) -> List[TradingSignal]:
        """Generate trading signals (simplified version)."""
        signals: List[TradingSignal] = []

        try:
            if len(data) < 50:
                return signals

            # Calculate indicators
            ema_21 = self.indicators.ema(data["close"], 21)
            rsi = self.indicators.rsi(
                data["close"], self.config.strategy.signals.rsi_period
            )
            donchian_high, donchian_low = self.indicators.donchian_channels(
                data, self.config.strategy.signals.donchian_period
            )

            # Current values
            current_price = data["close"].iloc[-1]
            current_ema21 = ema_21.iloc[-1]
            current_rsi = rsi.iloc[-1]
            current_high = donchian_high.iloc[-1]
            current_low = donchian_low.iloc[-1]

            # Pullback signals
            if (
                abs(current_price - current_ema21) / current_ema21 < 0.005
                and current_rsi < self.config.strategy.signals.rsi_oversold
            ):

                signals.append(
                    TradingSignal(
                        signal_type="pullback",
                        direction="long",
                        strength=0.7,
                        confidence=0.6,
                        entry_price=current_price,
                        stop_loss=current_price * 0.98,
                        take_profit=current_price * 1.04,
                    )
                )

            # Breakout signals
            if current_price > current_high:
                signals.append(
                    TradingSignal(
                        signal_type="breakout",
                        direction="long",
                        strength=0.8,
                        confidence=0.7,
                        entry_price=current_price,
                        stop_loss=current_low,
                        take_profit=current_price + 2 * (current_price - current_low),
                    )
                )

        except Exception as e:
            logger.error(f"Error generating signals: {e}")

        return signals

    def _filter_signals(
        self, signals: List[TradingSignal], regime: MarketRegime, setup: TradingSetup
    ) -> List[TradingSignal]:
        """Filter signals based on regime and setup."""
        valid_signals = []

        for signal in signals:
            # Check regime alignment
            regime_aligned = (
                signal.direction == "long" and regime.regime in ["bullish", "neutral"]
            ) or (
                signal.direction == "short" and regime.regime in ["bearish", "neutral"]
            )

            # Check setup alignment
            setup_aligned = (
                setup.direction == "none" or signal.direction == setup.direction
            )

            if regime_aligned and setup_aligned:
                valid_signals.append(signal)

        return valid_signals

    def _calculate_confidence(
        self, regime: MarketRegime, setup: TradingSetup, signal: TradingSignal
    ) -> float:
        """Calculate confidence score."""
        regime_score = regime.confidence * self.config.strategy.regime.weight * 100
        setup_score = (
            (setup.quality * setup.strength) * self.config.strategy.setup.weight * 100
        )
        signal_score = (
            (signal.strength * signal.confidence)
            * self.config.strategy.signals.weight
            * 100
        )

        total_score = regime_score + setup_score + signal_score
        return max(0, min(100, total_score))

    async def _execute_signal(
        self, symbol: str, signal: TradingSignal, confidence: float, timestamp: datetime
    ):
        """Execute trading signal in backtest."""
        try:
            # Check if we can take new positions
            if len(self.positions) >= self.config.trading.max_positions:
                return

            # Check if already have position in this symbol
            if symbol in self.positions:
                return

            # Calculate position size
            risk_amount = self.current_balance * self.config.trading.risk_per_trade
            price_diff = abs(signal.entry_price - signal.stop_loss)

            if price_diff <= 0:
                return

            position_size = risk_amount / price_diff

            # Adjust for confidence
            if confidence < self.config.strategy.confidence.full_size_threshold:
                position_size *= 0.7

            # Apply slippage
            entry_price = signal.entry_price * (
                1 + self.slippage if signal.direction == "long" else 1 - self.slippage
            )

            # Calculate commission
            commission = position_size * entry_price * self.commission

            # Create position
            self.positions[symbol] = {
                "direction": signal.direction,
                "size": position_size,
                "entry_price": entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "entry_time": timestamp,
                "commission": commission,
            }

            # Update balance
            self.current_balance -= commission

            logger.info(
                f"Opened {signal.direction} position in {symbol}: {position_size:.4f} @ ${entry_price:.2f}"
            )

        except Exception as e:
            logger.error(f"Error executing signal: {e}")

    def _update_positions(self, symbol: str, current_bar: pd.Series):
        """Update positions based on current market data."""
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        current_price = current_bar["close"]

        # Check stop loss
        if (
            position["direction"] == "long" and current_price <= position["stop_loss"]
        ) or (
            position["direction"] == "short" and current_price >= position["stop_loss"]
        ):

            self._close_position(symbol, current_price, "stop_loss")
            return

        # Check take profit
        if (
            position["direction"] == "long" and current_price >= position["take_profit"]
        ) or (
            position["direction"] == "short"
            and current_price <= position["take_profit"]
        ):

            self._close_position(symbol, current_price, "take_profit")
            return

    def _close_position(self, symbol: str, exit_price: float, reason: str):
        """Close a position."""
        if symbol not in self.positions:
            return

        position = self.positions[symbol]

        # Apply slippage
        exit_price = exit_price * (
            1 - self.slippage if position["direction"] == "long" else 1 + self.slippage
        )

        # Calculate P&L
        if position["direction"] == "long":
            pnl = (exit_price - position["entry_price"]) * position["size"]
        else:
            pnl = (position["entry_price"] - exit_price) * position["size"]

        # Calculate commission
        commission = position["size"] * exit_price * self.commission
        net_pnl = pnl - position["commission"] - commission

        # Update balance
        self.current_balance += net_pnl

        # Record trade
        trade = {
            "symbol": symbol,
            "direction": position["direction"],
            "size": position["size"],
            "entry_price": position["entry_price"],
            "exit_price": exit_price,
            "entry_time": position["entry_time"],
            "exit_time": datetime.now(),
            "pnl": pnl,
            "commission": position["commission"] + commission,
            "net_pnl": net_pnl,
            "reason": reason,
        }

        self.trades.append(trade)

        # Update statistics
        self.total_trades += 1
        self.total_pnl += net_pnl

        if net_pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

        # Remove position
        del self.positions[symbol]

        logger.info(
            f"Closed {position['direction']} position in {symbol}: P&L ${net_pnl:.2f} ({reason})"
        )

    def _record_equity(self, timestamp: datetime):
        """Record current equity."""
        # Calculate unrealized P&L
        unrealized_pnl = 0.0
        # Note: In a real backtest, you'd calculate unrealized P&L for open positions

        total_equity = self.current_balance + unrealized_pnl

        # Update peak equity and drawdown
        if total_equity > self.peak_equity:
            self.peak_equity = total_equity

        current_drawdown = (self.peak_equity - total_equity) / self.peak_equity
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown

        # Record equity point
        self.equity_curve.append(
            {
                "timestamp": timestamp,
                "balance": self.current_balance,
                "equity": total_equity,
                "drawdown": current_drawdown,
            }
        )

    def _calculate_performance(self) -> Dict:
        """Calculate performance metrics."""
        if self.total_trades == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "trades": [],
                "equity_curve": [],
            }

        # Calculate metrics
        win_rate = (self.winning_trades / self.total_trades) * 100

        # Profit factor
        gross_profit = sum(
            trade["net_pnl"] for trade in self.trades if trade["net_pnl"] > 0
        )
        gross_loss = abs(
            sum(trade["net_pnl"] for trade in self.trades if trade["net_pnl"] < 0)
        )
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Sharpe ratio (simplified)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                prev_equity = self.equity_curve[i - 1]["equity"]
                curr_equity = self.equity_curve[i]["equity"]
                if prev_equity > 0:
                    returns.append((curr_equity - prev_equity) / prev_equity)

            if returns:
                avg_return = np.mean(returns)
                std_return = np.std(returns)
                sharpe_ratio = (
                    (avg_return / std_return) * np.sqrt(252) if std_return > 0 else 0.0
                )
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0

        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "total_pnl": self.total_pnl,
            "profit_factor": profit_factor,
            "max_drawdown": self.max_drawdown * 100,
            "sharpe_ratio": sharpe_ratio,
            "final_balance": self.current_balance,
            "return_percentage": (
                (self.current_balance - self.initial_balance) / self.initial_balance
            )
            * 100,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
        }


async def main():
    """Main backtest function."""
    parser = argparse.ArgumentParser(description="Crypto Trading Bot Backtester")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol to backtest")
    parser.add_argument("--start", default="2023-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2024-01-01", help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", default="backtest_results.json", help="Output file")

    args = parser.parse_args()

    try:
        # Load configuration
        config = get_config()

        # Create backtest engine
        engine = BacktestEngine(config)

        # Run backtest
        results = await engine.run_backtest(args.symbol, args.start, args.end)

        if results:
            # Save results
            with open(args.output, "w") as f:
                # Convert datetime objects to strings for JSON serialization
                json_results = results.copy()
                for trade in json_results.get("trades", []):
                    if "entry_time" in trade and isinstance(
                        trade["entry_time"], datetime
                    ):
                        trade["entry_time"] = trade["entry_time"].isoformat()
                    if "exit_time" in trade and isinstance(
                        trade["exit_time"], datetime
                    ):
                        trade["exit_time"] = trade["exit_time"].isoformat()

                for point in json_results.get("equity_curve", []):
                    if "timestamp" in point and isinstance(
                        point["timestamp"], datetime
                    ):
                        point["timestamp"] = point["timestamp"].isoformat()

                json.dump(json_results, f, indent=2)

            # Print summary
            print(f"\n{'='*50}")
            print(f"BACKTEST RESULTS - {args.symbol}")
            print(f"{'='*50}")
            print(f"Period: {args.start} to {args.end}")
            print(f"Total Trades: {results['total_trades']}")
            print(f"Win Rate: {results['win_rate']:.1f}%")
            print(f"Total P&L: ${results['total_pnl']:.2f}")
            print(f"Return: {results['return_percentage']:.1f}%")
            print(f"Profit Factor: {results['profit_factor']:.2f}")
            print(f"Max Drawdown: {results['max_drawdown']:.1f}%")
            print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
            print(f"Final Balance: ${results['final_balance']:.2f}")
            print(f"\nResults saved to: {args.output}")
        else:
            print("Backtest failed - no results generated")

    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
