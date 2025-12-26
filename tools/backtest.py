"""
Historical backtesting engine with realistic execution simulation.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.config import TradingBotConfig, get_config
from src.database import DatabaseManager
from src.dynamic_strategy import DynamicStrategyEngine, StrategyConfig
from src.exchange import ExchangeClient
from src.indicators import TechnicalIndicators
from src.models import MarketSnapshot, Side
from src.paper_trader import PaperBroker
from src.strategy import MarketRegime, TradingSetup, TradingSignal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VirtualClock:
    def __init__(self):
        self._current_time = datetime.now(timezone.utc)

    def set_time(self, dt: datetime):
        self._current_time = dt

    def now(self) -> datetime:
        return self._current_time


class BacktestEngine:
    def __init__(
        self, config: TradingBotConfig, strategy_config: Optional[StrategyConfig] = None
    ):
        self.config = config
        self.strategy_config = strategy_config
        self.indicators = TechnicalIndicators()

        # Initialize dynamic engine if config is provided
        self.dynamic_engine: Optional[DynamicStrategyEngine] = None
        if self.strategy_config:
            self.dynamic_engine = DynamicStrategyEngine(self.strategy_config)

        self.initial_balance = config.backtesting.initial_balance

        self.clock = VirtualClock()
        self.database = DatabaseManager(":memory:")

        # Initialize PaperBroker for backtesting
        # We use the config's paper settings but override mode to 'backtest'
        self.broker = PaperBroker(
            config=config.paper,
            database=self.database,
            mode="backtest",
            run_id=f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            initial_balance=config.backtesting.initial_balance,
            risk_config=config.risk_management,
            time_provider=self.clock.now,
        )

        self.equity_curve: List[Dict] = []

        # Performance metrics (will be calculated from DB)
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.peak_equity = config.backtesting.initial_balance

    async def run_backtest(self, symbol: str, start_date: str, end_date: str) -> Dict:
        """Run backtest for a symbol over date range."""
        try:
            logger.info(
                f"Starting backtest for {symbol} from {start_date} to {end_date}"
            )

            # Initialize database
            await self.database.initialize()

            # Initialize exchange client for data fetching
            exchange = ExchangeClient(
                self.config.exchange,
                app_mode="paper",
                paper_broker=self.broker,
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
            await self._simulate_trading(symbol, data, start_date)

            # Calculate performance metrics
            performance = await self._calculate_performance()

            # Close exchange
            await exchange.close()

            logger.info(
                f"Backtest completed. Total P&L: ${performance.get('total_pnl', 0.0):.2f}"
            )

            return performance

        except Exception as e:
            logger.error(f"Backtest error: {e}")
            import traceback

            traceback.print_exc()
            return {}
        finally:
            await self.database.close()

    async def _fetch_historical_data(
        self, exchange: ExchangeClient, symbol: str, start_date: str, end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """Fetch historical data for all required timeframes."""
        data: Dict[str, pd.DataFrame] = {}

        try:
            start_dt = pd.Timestamp(start_date).tz_localize("UTC")
            end_dt = pd.Timestamp(end_date).tz_localize("UTC")
            days_diff = max((end_dt - start_dt).days, 1)

            missing_timeframes: List[str] = []
            for tf_name, timeframe in self.config.data.timeframes.model_dump().items():
                logger.info("Fetching %s data for %s", timeframe, symbol)

                if timeframe == "1h":
                    limit = min(days_diff * 24 + 200, 1000)
                elif timeframe == "4h":
                    limit = min(days_diff * 6 + 100, 1000)
                elif timeframe.lower() in {"1d", "1day", "1daily"}:
                    limit = min(days_diff + 50, 1000)
                else:
                    limit = 1000

                df = await exchange.get_historical_data(symbol, timeframe, limit)
                df = self._normalise_dataframe(df)
                if df is None or df.empty:
                    df = self._load_local_klines(symbol, timeframe)

                if df is None or df.empty:
                    logger.warning("No data available for %s (%s)", tf_name, timeframe)
                    missing_timeframes.append(tf_name)
                    continue

                # Include buffer for warmup (e.g. 30 days)
                buffer_dt = start_dt - pd.Timedelta(days=250)
                sliced = df[(df.index >= buffer_dt) & (df.index <= end_dt)]
                if sliced.empty:
                    logger.warning(
                        "No observations between %s and %s for %s (%s)",
                        buffer_dt,
                        end_date,
                        tf_name,
                        timeframe,
                    )
                    missing_timeframes.append(tf_name)
                    continue

                data[tf_name] = sliced
                logger.info("Loaded %s rows for %s", len(sliced), timeframe)

            if missing_timeframes:
                raise RuntimeError(
                    f"Missing historical data for timeframes: {', '.join(missing_timeframes)}"
                )

            return data

        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return {}

    def _normalise_dataframe(
        self, df: Optional[pd.DataFrame]
    ) -> Optional[pd.DataFrame]:
        if df is None or df.empty:
            return None
        frame = df.copy()
        timestamp_col = None
        for candidate in ("timestamp", "time", "datetime", "date"):
            if candidate in frame.columns:
                timestamp_col = candidate
                break
        if timestamp_col is None:
            return None
        frame[timestamp_col] = pd.to_datetime(
            frame[timestamp_col], utc=True, errors="coerce"
        )
        frame.dropna(subset=[timestamp_col], inplace=True)
        frame.set_index(timestamp_col, inplace=True)
        frame.sort_index(inplace=True)
        return frame

    def _load_local_klines(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Load historical data from local sample/replay files."""

        def _strip_scheme(path_str: str) -> str:
            for prefix in ("parquet://", "csv://"):
                if path_str.startswith(prefix):
                    return path_str[len(prefix) :]
            return path_str

        candidates: List[Path] = []
        replay_source = (self.config.replay.source or "").strip()
        if replay_source:
            candidates.append(Path(_strip_scheme(replay_source)))

        symbol_slug = symbol.lower()
        timeframe_slug = timeframe.lower()
        base_names = [
            f"{symbol_slug}_{timeframe_slug}",
            f"{symbol.upper()}_{timeframe}",
            f"{symbol}_{timeframe_slug}",
        ]
        search_roots = [
            Path("data") / "historical",
            Path("data") / "history",
            Path("data"),
            Path("sample_data"),
        ]

        for root in search_roots:
            for name in base_names:
                candidates.append(root / f"{name}.parquet")
                candidates.append(root / f"{name}.csv")

        for path in candidates:
            dataset = self._read_local_dataset(path, symbol)
            if dataset is not None and not dataset.empty:
                logger.info("Loaded %s bars from %s", len(dataset), path)
                return dataset

        logger.warning(
            "Local dataset not found for %s %s (checked %s candidates)",
            symbol,
            timeframe,
            len(candidates),
        )
        return None

    def _read_local_dataset(self, path: Path, symbol: str) -> Optional[pd.DataFrame]:
        if not path.exists():
            return None
        try:
            if path.suffix.lower() == ".parquet":
                df = pd.read_parquet(path)
            elif path.suffix.lower() in {".csv", ".txt"}:
                df = pd.read_csv(path)
            else:
                return None
        except Exception as exc:
            logger.warning("Unable to read %s: %s", path, exc)
            return None

        normalized = self._normalise_dataframe(df)
        if normalized is None or normalized.empty:
            return None
        df = normalized

        if "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == symbol.upper()]

        return df if not df.empty else None

    async def _simulate_trading(
        self, symbol: str, data: Dict[str, pd.DataFrame], start_date_str: str
    ):
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
                self.clock.set_time(current_time)

                # Check if we are within the requested backtest window
                # (Data includes warmup buffer)
                start_dt_limit = pd.Timestamp(start_date_str).tz_localize("UTC")
                if current_time < start_dt_limit:
                    continue

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

                # OHLC Interpolation for PaperBroker
                # We feed Open, then High/Low, then Close to ensure stops/limits are triggered
                row = signal_data.iloc[i]
                open_p = row.get("open", row["close"])
                high_p = row.get("high", row["close"])
                low_p = row.get("low", row["close"])
                close_p = row["close"]
                vol = row.get("volume", 0)

                # Determine path: O -> L -> H -> C (Green) or O -> H -> L -> C (Red)
                # This is a heuristic.
                is_green = close_p >= open_p
                path = [open_p]
                if is_green:
                    path.extend([low_p, high_p])
                else:
                    path.extend([high_p, low_p])
                path.append(close_p)

                # Feed snapshots
                for price in path:
                    snapshot = MarketSnapshot(
                        symbol=symbol,
                        best_bid=price - 0.01,  # Tight spread approximation
                        best_ask=price + 0.01,
                        bid_size=vol / 4,
                        ask_size=vol / 4,
                        last_price=price,
                        timestamp=current_time,
                    )
                    await self.broker.update_market(snapshot)
                    # Allow broker to process fills
                    await asyncio.sleep(0)

                # Analyze market and generate signals (at Close)
                await self._analyze_market(symbol, current_data, current_time)

                # Allow broker to process any new orders
                await asyncio.sleep(0)

                # Record equity
                await self._record_equity(current_time)

                # Progress logging
                if i % 100 == 0:
                    progress = (i / len(signal_data)) * 100
                    balance = (await self.broker.get_account_balance())[
                        "totalWalletBalance"
                    ]
                    logger.info(f"Progress: {progress:.1f}% - Balance: ${balance:.2f}")

        except Exception as e:
            logger.error(f"Error in trading simulation: {e}")
            import traceback

            traceback.print_exc()

    async def _analyze_market(
        self, symbol: str, data: Dict[str, pd.DataFrame], current_time: datetime
    ):
        """Analyze market conditions and generate signals."""
        try:
            # 1. Regime Detection
            regime: Optional[MarketRegime]
            if self.dynamic_engine:
                regime = self.dynamic_engine.detect_regime(data["regime"])
            else:
                regime = self._detect_regime(data["regime"])

            # 2. Setup Detection
            setup: Optional[TradingSetup]
            if self.dynamic_engine:
                setup = self.dynamic_engine.detect_setup(data["setup"])
            else:
                setup = self._detect_setup(data["setup"])

            # 3. Signal Generation
            if self.dynamic_engine:
                signals = self.dynamic_engine.generate_signals(data["signal"])
            else:
                signals = self._generate_signals(data["signal"])

            # 4. Filter and score signals
            if regime and setup and signals:
                # Note: Dynamic engine might handle filtering differently, but we'll stick to the flow
                valid_signals = self._filter_signals(signals, regime, setup)

                for signal in valid_signals:
                    if self.dynamic_engine:
                        confidence_score = self.dynamic_engine.calculate_confidence(
                            regime, setup, signal
                        )
                        confidence_value = confidence_score.total_score
                        threshold = self.dynamic_engine.config.confidence_threshold
                    else:
                        confidence_value = self._calculate_confidence(
                            regime, setup, signal
                        )
                        threshold = self.config.strategy.confidence.min_threshold

                    if confidence_value >= threshold:
                        await self._execute_signal(
                            symbol, signal, confidence_value, current_time
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
            # Check current positions
            positions = await self.broker.get_positions()

            # Check if we can take new positions
            if len(positions) >= self.config.trading.max_positions:
                return

            # Check if already have position in this symbol
            if any(p.symbol == symbol for p in positions):
                return

            # Get current balance
            balance = (await self.broker.get_account_balance())["totalWalletBalance"]

            # Calculate position size
            risk_amount = balance * self.config.trading.risk_per_trade
            price_diff = abs(signal.entry_price - signal.stop_loss)

            if price_diff <= 0:
                return

            position_size = risk_amount / price_diff

            # Adjust for confidence
            if confidence < self.config.strategy.confidence.full_size_threshold:
                position_size *= 0.7

            # Convert direction
            side: Side = "buy" if signal.direction == "long" else "sell"

            # Place Entry Order
            await self.broker.place_order(
                symbol=symbol,
                side=side,
                order_type="market",
                quantity=position_size,
                client_id=f"entry-{timestamp.timestamp()}",
            )

            # Place Stop Loss Order
            stop_side: Side = "sell" if side == "buy" else "buy"
            await self.broker.place_order(
                symbol=symbol,
                side=stop_side,
                order_type="stop_market",
                quantity=position_size,
                stop_price=signal.stop_loss,
                reduce_only=True,
                client_id=f"stop-{timestamp.timestamp()}",
            )

            # Place Take Profit Order (Limit)
            await self.broker.place_order(
                symbol=symbol,
                side=stop_side,
                order_type="limit",
                quantity=position_size,
                price=signal.take_profit,
                reduce_only=True,
                client_id=f"tp-{timestamp.timestamp()}",
            )

            logger.info(
                f"Placed {side} order for {symbol}: {position_size:.4f} @ Market (SL: {signal.stop_loss}, TP: {signal.take_profit})"
            )

        except Exception as e:
            logger.error(f"Error executing signal: {e}")
            import traceback

            traceback.print_exc()

    async def _record_equity(self, timestamp: datetime):
        """Record current equity."""
        balance_info = await self.broker.get_account_balance()
        balance = balance_info["totalWalletBalance"]

        # Get unrealized PnL from positions
        positions = await self.broker.get_positions()
        unrealized_pnl = sum(p.unrealized_pnl for p in positions)

        total_equity = balance + unrealized_pnl

        # Update peak equity and drawdown
        if total_equity > self.peak_equity:
            self.peak_equity = total_equity

        current_drawdown = 0.0
        if self.peak_equity > 0:
            current_drawdown = (self.peak_equity - total_equity) / self.peak_equity

        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown

        # Record equity point
        self.equity_curve.append(
            {
                "timestamp": timestamp,
                "balance": balance,
                "equity": total_equity,
                "drawdown": current_drawdown,
            }
        )

    async def _calculate_performance(self) -> Dict:
        """Calculate performance metrics."""

        # Fetch trades from DB
        trades_models = await self.database.get_trades(run_id=self.broker.run_id)

        # Convert to dicts for consistency with legacy format
        trades = []
        for t in trades_models:
            trade_dict = t.model_dump()
            # Ensure timestamps are strings
            if isinstance(trade_dict.get("timestamp"), datetime):
                trade_dict["timestamp"] = trade_dict["timestamp"].isoformat()

            # Calculate net_pnl
            trade_dict["net_pnl"] = (
                trade_dict.get("realized_pnl", 0.0)
                - trade_dict.get("commission", 0.0)
                - trade_dict.get("fees", 0.0)
                - trade_dict.get("funding", 0.0)
            )
            trades.append(trade_dict)

        self.total_trades = len(trades)
        self.winning_trades = sum(1 for t in trades if t["net_pnl"] > 0)
        self.losing_trades = sum(1 for t in trades if t["net_pnl"] <= 0)
        self.total_pnl = sum(t["net_pnl"] for t in trades)

        balance_info = await self.broker.get_account_balance()
        current_balance = balance_info["totalWalletBalance"]

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
                "final_balance": current_balance,
                "return_percentage": 0.0,
                "trades": [],
                "equity_curve": [],
            }

        # Calculate metrics
        win_rate = (self.winning_trades / self.total_trades) * 100

        # Profit factor
        gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        gross_loss = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
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
                    (avg_return / std_return) * np.sqrt(252 * 24)
                    if std_return > 0
                    else 0.0  # Assuming hourly bars
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
            "final_balance": current_balance,
            "return_percentage": (
                (current_balance - self.initial_balance) / self.initial_balance
            )
            * 100,
            "trades": trades,
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

        print(f"DynamicStrategyEngine available: {DynamicStrategyEngine is not None}")
        print(f"DB Path: {config.database.path}")

        strategy_config = None
        # Try to load active strategy from real DB
        try:
            db_path = config.database.path
            if Path(db_path).exists():
                print(f"DB file exists at {db_path}")
                # We need to import DatabaseManager here or use the one imported
                # It is already imported.
                db = DatabaseManager(db_path)
                await db.initialize()
                strategies = await db.list_strategies()
                print(f"Found {len(strategies)} strategies in DB")
                active = [s for s in strategies if s.is_active]
                print(f"Found {len(active)} active strategies")
                if active:
                    # Convert DB strategy to StrategyConfig
                    from src.strategy import db_row_to_strategy_config

                    strategy_config = db_row_to_strategy_config(active[0])
                    print(f"Loaded active strategy: {strategy_config.name}")
                await db.close()
            else:
                print(f"DB file does not exist at {db_path}")
        except Exception as e:
            print(f"Failed to load strategy from DB: {e}")
            import traceback

            traceback.print_exc()

        # Create backtest engine
        engine = BacktestEngine(config, strategy_config)

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
