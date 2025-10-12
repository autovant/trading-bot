"""
Complete trading strategy implementation with regime detection, confidence scoring,
ladder entries, dual stops, and crisis mode.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel

from .config import TradingBotConfig
from .database import DatabaseManager, Order, Position, Trade
from .exchange import ExchangeClient, OrderResponse, Side, OrderType
from .indicators import TechnicalIndicators
from .messaging import MessagingClient
from .paper_trader import MarketSnapshot, PaperBroker

logger = logging.getLogger(__name__)


class MarketRegime(BaseModel):
    """Market regime classification."""

    regime: str  # 'bullish', 'bearish', 'neutral'
    strength: float  # 0-1
    confidence: float  # 0-1


class TradingSetup(BaseModel):
    """Trading setup classification."""

    direction: str  # 'long', 'short', 'none'
    quality: float  # 0-1
    strength: float  # 0-1


class TradingSignal(BaseModel):
    """Trading signal with metadata."""

    signal_type: str  # 'pullback', 'breakout', 'divergence'
    direction: str  # 'long', 'short'
    strength: float  # 0-1
    confidence: float  # 0-1
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: Optional[datetime] = None


class ConfidenceScore(BaseModel):
    """Confidence scoring breakdown."""

    regime_score: float
    setup_score: float
    signal_score: float
    penalty_score: float
    total_score: float


class TradingStrategy:
    """Main trading strategy implementation."""

    def __init__(
        self,
        config: TradingBotConfig,
        exchange: ExchangeClient,
        database: DatabaseManager,
        messaging: Optional[MessagingClient] = None,
        paper_broker: Optional[PaperBroker] = None,
        run_id: str = "",
    ):
        self.config = config
        self.exchange = exchange
        self.database = database
        self.messaging = messaging
        self.paper_broker = paper_broker
        self.run_id = run_id or datetime.utcnow().strftime("%Y%m%d%H%M%S")
        self.mode = self.config.app_mode
        self.indicators = TechnicalIndicators()

        # Strategy state
        self.market_data: Dict[str, Dict[str, pd.DataFrame]] = {}
        self.active_positions: Dict[str, Position] = {}
        self.pending_orders: List[OrderResponse] = []
        self.crisis_mode = False
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.risk_state = None

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.peak_equity = self.config.trading.initial_capital

        # Subscribe to risk state updates
        if self.messaging:
            asyncio.create_task(self._subscribe_to_risk_updates())
            asyncio.create_task(self._subscribe_to_execution_reports())

    async def _subscribe_to_execution_reports(self):
        """Subscribe to execution reports from the messaging system."""
        try:
            if self.messaging:
                await self.messaging.subscribe(
                    self.config.messaging.subjects["executions"],
                    self._handle_execution_report,
                )
                await self.messaging.subscribe(
                    self.config.messaging.subjects["executions_shadow"],
                    self._handle_execution_report,
                )
        except Exception as e:
            logger.error(f"Error subscribing to execution reports: {e}")

    async def _handle_execution_report(self, msg):
        """Handle execution reports received from the messaging system."""
        try:
            report = json.loads(msg.data)
            is_shadow = report.get("is_shadow", False)

            if report["executed"]:
                trade = Trade(
                    client_id=report.get("client_id", report["order_id"]),
                    trade_id=report["order_id"],
                    order_id=report["order_id"],
                    symbol=report["symbol"],
                    side=report["side"],
                    quantity=report["quantity"],
                    price=report["price"],
                    commission=report.get("commission", 0.0),
                    fees=report.get("fees", 0.0),
                    funding=report.get("funding", 0.0),
                    realized_pnl=report.get("realized_pnl", 0.0),
                    mark_price=report.get("mark_price", report["price"]),
                    slippage_bps=report.get("slippage_bps", 0.0),
                    latency_ms=report.get("latency_ms", 0.0),
                    maker=report.get("maker", False),
                    mode=self.mode,
                    run_id=self.run_id,
                    timestamp=datetime.fromisoformat(report["timestamp"]),
                    is_shadow=is_shadow,
                )
                await self.database.create_trade(trade)
                order_status = "filled"
            else:
                order_status = "rejected"

            await self.database.update_order_status(
                report["order_id"], order_status, is_shadow
            )

        except Exception as e:
            logger.error(f"Error handling execution report: {e}")

    async def update_market_data(self):
        """Update market data for all symbols and timeframes."""
        try:
            market_updates = []

            for symbol in self.config.trading.symbols:
                if symbol not in self.market_data:
                    self.market_data[symbol] = {}

                signal_snapshot: Optional[MarketSnapshot] = None

                # Fetch data for each timeframe
                for tf_name, timeframe in self.config.data.timeframes.items():
                    lookback = self.config.data.lookback_periods[tf_name]

                    # Fetch OHLCV data
                    data = await self.exchange.get_historical_data(
                        symbol=symbol, timeframe=timeframe, limit=lookback
                    )

                    if data is not None and not data.empty:
                        self.market_data[symbol][tf_name] = data
                        logger.debug(
                            f"Updated {symbol} {timeframe} data: {len(data)} bars"
                        )

                        if tf_name == "signal":
                            signal_snapshot = self._build_market_snapshot(symbol, data)

                        # Collect market data for publishing
                        market_updates.append(
                            {
                                "symbol": symbol,
                                "timeframe": tf_name,
                                "timestamp": datetime.now().isoformat(),
                                "data": {
                                    "open": float(data["open"].iloc[-1]),
                                    "high": float(data["high"].iloc[-1]),
                                    "low": float(data["low"].iloc[-1]),
                                    "close": float(data["close"].iloc[-1]),
                                    "volume": float(data["volume"].iloc[-1]),
                                },
                            }
                        )

                if self.paper_broker and signal_snapshot:
                    await self.paper_broker.update_market(signal_snapshot)

            # Publish market data to messaging system
            if self.messaging and market_updates:
                await self.messaging.publish(
                    self.config.messaging.subjects["market_data"],
                    {
                        "type": "market_data_update",
                        "timestamp": datetime.now().isoformat(),
                        "updates": market_updates,
                    },
                )

        except Exception as e:
            logger.error(f"Error updating market data: {e}")

    async def run_analysis(self):
        """Run the trading analysis loop for all symbols."""
        for symbol in self.config.trading.symbols:
            await self._analyze_symbol(symbol)

    def _build_market_snapshot(self, symbol: str, data: pd.DataFrame) -> MarketSnapshot:
        last = data.iloc[-1]
        close = float(last["close"])
        open_price = float(last["open"])
        high = float(last["high"])
        low = float(last["low"])
        volume = float(last["volume"])
        spread = max(close * 0.0005, abs(high - low) * 0.1)
        best_bid = max(close - spread / 2, 0.0)
        best_ask = close + spread / 2
        last_side: Side = "buy" if close >= open_price else "sell"
        snapshot = MarketSnapshot(
            symbol=symbol,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=max(volume * 0.25, 1.0),
            ask_size=max(volume * 0.25, 1.0),
            last_price=close,
            last_side=last_side,
            last_size=max(volume * 0.1, 1.0),
            funding_rate=0.0,
            timestamp=datetime.utcnow(),
        )
        return snapshot

    def _generate_client_id(self, symbol: str) -> str:
        return f"{self.run_id}-{symbol}-{datetime.utcnow().strftime('%H%M%S%f')}"

    def _direction_to_side(self, direction: str) -> Side:
        return "buy" if direction.lower() in ("long", "buy") else "sell"

    async def _record_order_ack(self, response: OrderResponse) -> None:
        if self.mode != "live":
            return
        order = Order(
            client_id=response.client_id,
            order_id=response.order_id,
            symbol=response.symbol,
            side=response.side,
            order_type=response.order_type,
            quantity=response.quantity,
            price=response.price,
            status=response.status,
            created_at=response.timestamp,
            mode=self.mode,
            run_id=self.run_id,
        )
        await self.database.create_order(order)

    async def _analyze_symbol(self, symbol: str):
        """Run the full analysis pipeline for a single symbol."""
        try:
            # Get market data
            regime_data = self.market_data[symbol].get("regime")
            setup_data = self.market_data[symbol].get("setup")
            signal_data = self.market_data[symbol].get("signal")

            if regime_data is None or regime_data.empty:
                logger.warning(f"Incomplete regime data for {symbol}")
                return
            if setup_data is None or setup_data.empty:
                logger.warning(f"Incomplete setup data for {symbol}")
                return
            if signal_data is None or signal_data.empty:
                logger.warning(f"Incomplete signal data for {symbol}")
                return

            # 1. Regime Detection
            regime = self._detect_regime(regime_data)

            # 2. Setup Detection
            setup = self._detect_setup(setup_data)

            # 3. Signal Generation
            signals = self._generate_signals(signal_data)

            # 4. Filter signals by regime and setup
            valid_signals = self._filter_signals(signals, regime, setup)

            # 5. Score and execute valid signals
            for signal in valid_signals:
                confidence = self._calculate_confidence(regime, setup, signal, symbol)

                if (
                    confidence.total_score
                    >= self.config.strategy.confidence.min_threshold
                ):
                    await self._execute_signal(symbol, signal, confidence, regime)

        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")

    def _detect_regime(self, data: pd.DataFrame) -> MarketRegime:
        """Detect market regime using daily timeframe."""
        try:
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

            # Calculate confidence based on alignment
            price_ema_align = (
                1.0 if (current_price > current_ema) == (current_macd > 0) else 0.3
            )
            confidence = strength * price_ema_align

            return MarketRegime(regime=regime, strength=strength, confidence=confidence)

        except Exception as e:
            logger.error(f"Error detecting regime: {e}")
            return MarketRegime(regime="neutral", strength=0.5, confidence=0.5)

    def _detect_setup(self, data: pd.DataFrame) -> TradingSetup:
        """Detect trading setup using 4-hour timeframe."""
        try:
            # Calculate EMAs
            ema_8 = self.indicators.ema(
                data["close"], self.config.strategy.setup.ema_fast
            )
            ema_21 = self.indicators.ema(
                data["close"], self.config.strategy.setup.ema_medium
            )
            ema_55 = self.indicators.ema(
                data["close"], self.config.strategy.setup.ema_slow
            )

            # Calculate ADX and ATR
            adx = self.indicators.adx(data, self.config.strategy.setup.adx_period)
            atr = self.indicators.atr(data, self.config.strategy.setup.atr_period)

            # Current values
            current_price = data["close"].iloc[-1]
            current_ema8 = ema_8.iloc[-1]
            current_ema21 = ema_21.iloc[-1]
            current_ema55 = ema_55.iloc[-1]
            current_adx = adx.iloc[-1]
            current_atr = atr.iloc[-1]

            # Check EMA stack alignment
            bullish_stack = current_ema8 > current_ema21 > current_ema55
            bearish_stack = current_ema8 < current_ema21 < current_ema55

            # Check trend strength
            strong_trend = current_adx > self.config.strategy.setup.adx_threshold

            # Check price proximity to EMA8
            price_distance = abs(current_price - current_ema8)
            max_distance = current_atr * self.config.strategy.setup.atr_multiplier
            price_near_ema = price_distance <= max_distance

            # Determine setup
            if bullish_stack and strong_trend and price_near_ema:
                direction = "long"
                quality = min(1.0, current_adx / 50.0)  # Normalize ADX
                strength = 1.0 - (price_distance / max_distance)
            elif bearish_stack and strong_trend and price_near_ema:
                direction = "short"
                quality = min(1.0, current_adx / 50.0)
                strength = 1.0 - (price_distance / max_distance)
            else:
                direction = "none"
                quality = 0.0
                strength = 0.0

            return TradingSetup(direction=direction, quality=quality, strength=strength)

        except Exception as e:
            logger.error(f"Error detecting setup: {e}")
            return TradingSetup(direction="none", quality=0.0, strength=0.0)

    def _generate_signals(self, data: pd.DataFrame) -> List[TradingSignal]:
        """Generate trading signals using 1-hour timeframe."""
        signals = []

        try:
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

            # 1. Pullback Signals
            if (
                current_price <= current_ema21 * 1.005
                and current_price >= current_ema21 * 0.995
                and current_rsi < self.config.strategy.signals.rsi_oversold
            ):

                signals.append(
                    TradingSignal(
                        signal_type="pullback",
                        direction="long",
                        strength=0.8,
                        confidence=0.7,
                        entry_price=current_price,
                        stop_loss=current_price * 0.98,
                        take_profit=current_price * 1.04,
                        timestamp=datetime.now(),
                    )
                )

            elif (
                current_price <= current_ema21 * 1.005
                and current_price >= current_ema21 * 0.995
                and current_rsi > self.config.strategy.signals.rsi_overbought
            ):

                signals.append(
                    TradingSignal(
                        signal_type="pullback",
                        direction="short",
                        strength=0.8,
                        confidence=0.7,
                        entry_price=current_price,
                        stop_loss=current_price * 1.02,
                        take_profit=current_price * 0.96,
                        timestamp=datetime.now(),
                    )
                )

            # 2. Breakout Signals
            if current_price > current_high:
                signals.append(
                    TradingSignal(
                        signal_type="breakout",
                        direction="long",
                        strength=0.9,
                        confidence=0.8,
                        entry_price=current_price,
                        stop_loss=current_low,
                        take_profit=current_price + 2 * (current_price - current_low),
                        timestamp=datetime.now(),
                    )
                )

            elif current_price < current_low:
                signals.append(
                    TradingSignal(
                        signal_type="breakout",
                        direction="short",
                        strength=0.9,
                        confidence=0.8,
                        entry_price=current_price,
                        stop_loss=current_high,
                        take_profit=current_price - 2 * (current_high - current_price),
                        timestamp=datetime.now(),
                    )
                )

        except Exception as e:
            logger.error(f"Error generating signals: {e}")

        return signals

    def _filter_signals(
        self, signals: List[TradingSignal], regime: MarketRegime, setup: TradingSetup
    ) -> List[TradingSignal]:
        """Filter signals based on market regime and setup."""
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
                setup.direction == "none"  # No setup bias
                or signal.direction == setup.direction
            )

            if regime_aligned and setup_aligned:
                valid_signals.append(signal)

        return valid_signals

    def _calculate_confidence(
        self,
        regime: MarketRegime,
        setup: TradingSetup,
        signal: TradingSignal,
        symbol: str,
    ) -> ConfidenceScore:
        """Calculate confidence score for a trading signal."""

        # Regime score (0-25 points)
        regime_score = regime.confidence * self.config.strategy.regime.weight * 100

        # Setup score (0-30 points)
        setup_score = (
            (setup.quality * setup.strength) * self.config.strategy.setup.weight * 100
        )

        # Signal score (0-35 points)
        signal_score = (
            (signal.strength * signal.confidence)
            * self.config.strategy.signals.weight
            * 100
        )

        # Calculate penalties
        penalty_score = 0

        try:
            # High volatility penalty
            if symbol in self.market_data:
                signal_data = self.market_data[symbol].get("signal")
                if signal_data is not None:
                    atr = self.indicators.atr(signal_data, 14)
                    avg_atr = atr.rolling(50).mean().iloc[-1]
                    current_atr = atr.iloc[-1]

                    if current_atr > avg_atr * 2:
                        penalty_score += self.config.strategy.confidence.penalties[
                            "high_volatility"
                        ]

                    # Low volume penalty (if volume data available)
                    if "volume" in signal_data.columns:
                        avg_volume = signal_data["volume"].rolling(20).mean().iloc[-1]
                        current_volume = signal_data["volume"].iloc[-1]

                        if current_volume < avg_volume * 0.8:
                            penalty_score += self.config.strategy.confidence.penalties[
                                "low_volume"
                            ]

            # Conflicting timeframes penalty
            if regime.regime != "neutral" and setup.direction != "none":
                if (regime.regime == "bullish" and setup.direction == "short") or (
                    regime.regime == "bearish" and setup.direction == "long"
                ):
                    penalty_score += self.config.strategy.confidence.penalties[
                        "conflicting_timeframes"
                    ]

        except Exception as e:
            logger.error(f"Error calculating penalties: {e}")

        # Total score
        total_score = max(0, regime_score + setup_score + signal_score + penalty_score)

        return ConfidenceScore(
            regime_score=regime_score,
            setup_score=setup_score,
            signal_score=signal_score,
            penalty_score=penalty_score,
            total_score=total_score,
        )

    async def _execute_signal(
        self,
        symbol: str,
        signal: TradingSignal,
        confidence: ConfidenceScore,
        regime: MarketRegime,
    ):
        """Execute a trading signal with ladder entries and dual stops."""
        try:
            # Check if we can open a new position
            if len(self.active_positions) >= self.config.trading.max_positions:
                logger.info(f"Max positions reached, skipping {symbol}")
                return

            # Check if already have position in this symbol
            if symbol in self.active_positions:
                logger.info(f"Already have position in {symbol}, skipping signal")
                return

            # Calculate position size
            position_size = self._calculate_position_size(signal, confidence)
            if position_size <= 0:
                logger.info(f"Position size is zero, skipping {symbol}")
                return

            client_id = self._generate_client_id(symbol)
            side = self._direction_to_side(signal.direction)

            # If messaging is available, publish order via NATS
            if self.messaging:
                # Prepare order data for messaging
                order_data = {
                    "id": client_id,
                    "symbol": symbol,
                    "type": "limit",
                    "side": side,
                    "price": signal.entry_price,
                    "quantity": position_size,
                    "timestamp": datetime.now().isoformat(),
                }
                await self.messaging.publish(
                    self.config.messaging.subjects["orders"],
                    {
                        "type": "new_order",
                        "order": order_data,
                        "strategy_context": {
                            "confidence_score": confidence.total_score,
                            "signal_type": signal.signal_type,
                            "regime": regime.regime,
                        },
                    },
                )

            order_response = await self._place_order_directly(
                symbol=symbol,
                side=side,
                order_type="limit",
                quantity=position_size,
                price=signal.entry_price,
                client_id=client_id,
            )

            if order_response:
                logger.info(
                    "Placed order %s for %s: %s %.4f @ %.2f",
                    order_response.order_id,
                    symbol,
                    side,
                    position_size,
                    signal.entry_price,
                )
                await self._set_stop_losses(symbol, side, signal, position_size)
                await self.update_positions()

        except Exception as e:
            logger.error(f"Error executing signal for {symbol}: {e}")

    async def _place_order_directly(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        client_id: Optional[str] = None,
        is_shadow: bool = False,
    ) -> Optional[OrderResponse]:
        try:
            response = await self.exchange.place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                reduce_only=reduce_only,
                client_id=client_id,
                is_shadow=is_shadow,
            )
            if response:
                await self._record_order_ack(response)
                self.pending_orders.append(response)
            return response
        except Exception as exc:
            logger.error("Error placing order for %s: %s", symbol, exc)
            return None

    def _calculate_position_size(
        self, signal: TradingSignal, confidence: ConfidenceScore
    ) -> float:
        """Calculate position size based on risk and confidence."""
        try:
            # Get current account balance
            account_balance = self.config.trading.initial_capital + self.total_pnl

            # Adjust for crisis mode
            if self.crisis_mode:
                account_balance *= (
                    1 - self.config.risk_management.crisis_mode.position_size_reduction
                )

            # Base risk amount
            risk_amount = account_balance * self.config.trading.risk_per_trade

            # Adjust based on confidence
            if (
                confidence.total_score
                >= self.config.strategy.confidence.full_size_threshold
            ):
                size_multiplier = 1.0
            else:
                size_multiplier = 0.7  # Reduced size for lower confidence

            # Calculate position size
            price_diff = abs(signal.entry_price - signal.stop_loss)
            if price_diff <= 0:
                return 0

            position_size = (risk_amount * size_multiplier) / price_diff

            return position_size

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0

    async def _set_stop_losses(
        self, symbol: str, side: Side, signal: TradingSignal, position_size: float
    ):
        """Set dual stop loss system."""
        try:
            # Soft stop (composite)
            # soft_stop_price = signal.stop_loss

            # Hard stop (server-side)
            account_balance = self.config.trading.initial_capital + self.total_pnl
            max_loss = (
                account_balance * self.config.risk_management.stops.hard_risk_percent
            )

            hard_stop_price = signal.entry_price
            if side == "buy":
                hard_stop_price -= max_loss / position_size
            else:
                hard_stop_price += max_loss / position_size

            # Place hard stop order
            stop_order = await self._place_order_directly(
                symbol=symbol,
                side="sell" if side == "buy" else "buy",
                order_type="stop_market",
                quantity=position_size,
                stop_price=hard_stop_price,
                reduce_only=True,
                client_id=self._generate_client_id(symbol),
            )

            if stop_order:
                logger.info(f"Set hard stop for {symbol} at {hard_stop_price}")

        except Exception as e:
            logger.error(f"Error setting stops for {symbol}: {e}")

    async def _create_ladder_entries(
        self,
        symbol: str,
        signal: TradingSignal,
        total_size: float,
        confidence: ConfidenceScore,
    ):
        """Create ladder entry orders."""
        try:
            weights = self.config.risk_management.ladder_entries.weights
            side = self._direction_to_side(signal.direction)

            # Entry 1: Immediate at signal
            size_1 = total_size * weights[0]
            order_1 = await self._place_order_directly(
                symbol=symbol,
                side=side,
                order_type="market",
                quantity=size_1,
                client_id=self._generate_client_id(symbol),
            )

            if order_1:
                logger.info(f"Placed entry 1 for {symbol}: {size_1} @ market")

            # TODO: Implement additional ladder logic for entries 2/3

        except Exception as e:
            logger.error(f"Error creating ladder entries for {symbol}: {e}")

    async def update_positions(self):
        """Update active positions."""
        try:
            snapshots = await self.exchange.get_positions()

            for snapshot in snapshots:
                if isinstance(snapshot, Position):
                    db_position = snapshot
                else:
                    db_position = Position(
                        symbol=snapshot.symbol,
                        side=snapshot.side,
                        size=snapshot.size,
                        entry_price=snapshot.entry_price,
                        mark_price=snapshot.mark_price,
                        unrealized_pnl=snapshot.unrealized_pnl,
                        percentage=snapshot.percentage,
                        mode=self.mode,
                        run_id=self.run_id,
                        updated_at=datetime.utcnow(),
                    )

                self.active_positions[db_position.symbol] = db_position
                await self.database.update_position(db_position)

        except Exception as e:
            logger.error(f"Error updating positions: {e}")

    async def check_risk_management(self):
        """Check and enforce risk management rules."""
        try:
            # Calculate current metrics
            account_balance = self.config.trading.initial_capital + self.total_pnl
            current_drawdown = (
                (self.peak_equity - account_balance) / self.peak_equity
                if self.peak_equity > 0
                else 0
            )

            # Update peak equity
            if account_balance > self.peak_equity:
                self.peak_equity = account_balance

            # Check crisis mode triggers
            crisis_triggers = [
                current_drawdown
                > self.config.risk_management.crisis_mode.drawdown_threshold,
                self.consecutive_losses
                >= self.config.risk_management.crisis_mode.consecutive_losses,
                # TODO: Add volatility spike check
            ]

            if any(crisis_triggers) and not self.crisis_mode:
                await self._activate_crisis_mode()
            elif not any(crisis_triggers) and self.crisis_mode:
                await self._deactivate_crisis_mode()

            # Check daily risk limits
            if (
                abs(self.daily_pnl)
                > account_balance * self.config.trading.max_daily_risk
            ):
                logger.warning("Daily risk limit exceeded, closing all positions")
                await self.close_all_positions()

        except Exception as e:
            logger.error(f"Error checking risk management: {e}")

    async def _activate_crisis_mode(self):
        """Activate crisis mode."""
        self.crisis_mode = True
        logger.warning("CRISIS MODE ACTIVATED")

        # Reduce position sizes
        # Close weakest positions if needed
        # Increase confidence thresholds

    async def _deactivate_crisis_mode(self):
        """Deactivate crisis mode."""
        self.crisis_mode = False
        logger.info("Crisis mode deactivated")

    async def close_all_positions(self):
        """Close all active positions."""
        try:
            for symbol in list(self.active_positions.keys()):
                await self.exchange.close_position(symbol)
                logger.info(f"Closed position in {symbol}")

            self.active_positions.clear()

        except Exception as e:
            logger.error(f"Error closing positions: {e}")

    async def _subscribe_to_risk_updates(self):
        """Subscribe to risk management updates from the messaging system."""
        try:
            if self.messaging:
                # This is a placeholder for the actual subscription logic
                logger.info("Subscribing to risk updates.")
                # await self.messaging.subscribe(
                #     self.config.messaging.subjects['risk_updates'],
                #     self._handle_risk_update
                # )
        except Exception as e:
            logger.error(f"Error subscribing to risk updates: {e}")

    async def _wait_for_execution(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Wait for an execution result for a given order ID."""
        # This is a placeholder. In a real implementation, this would
        # listen on a NATS subject for a response from the execution service.
        logger.info(f"Waiting for execution of order {order_id}")
        await asyncio.sleep(1)  # Simulate network latency
        return {"executed": True}

    async def _publish_performance_metrics(self):
        """Publish performance metrics to messaging system."""
        if not self.messaging:
            return

        try:
            win_rate = (
                (self.winning_trades / self.total_trades * 100)
                if self.total_trades > 0
                else 0.0
            )

            metrics = {
                "total_trades": self.total_trades,
                "win_rate": win_rate,
                "total_pnl": self.total_pnl,
                "max_drawdown": self.max_drawdown,
                "current_equity": self.peak_equity + self.total_pnl,
                "timestamp": datetime.now().isoformat(),
            }

            await self.messaging.publish(
                self.config.messaging.subjects["performance"],
                {"type": "performance_metrics", "metrics": metrics},
            )
        except Exception as e:
            logger.error(f"Error publishing performance metrics: {e}")
