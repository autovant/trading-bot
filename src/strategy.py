"""
Complete trading strategy implementation with regime detection, confidence scoring,
ladder entries, dual stops, and crisis mode.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

import json
from .config import TradingBotConfig
from .database import DatabaseManager, Order, Position, Trade
from .dynamic_strategy import DynamicStrategyEngine
from .exchange import IExchange
from .indicators import TechnicalIndicators
from .messaging import MessagingClient
from .models import (
    ConfidenceScore,
    MarketRegime,
    MarketSnapshot,
    OrderResponse,
    PositionSnapshot,
    Side,
    TradingSignal,
)
from .orderbook_indicators import OrderBookIndicators
from .paper_trader import PaperBroker
from .position_manager import PositionManager
from .risk_manager import RiskManager
from .services.market_data_provider import MarketDataProvider
from .signal_generator import SignalGenerator
from .utils.decorators import handle_exceptions

logger = logging.getLogger(__name__)


class TradingStrategy:
    """
    Main trading strategy implementation.

    Orchestrates the entire trading lifecycle:
    1. Market Data Updates
    2. Signal Generation (Regime + Setup + Pattern)
    3. Risk Management Checks
    4. Execution (Ladder entries, Dual stops)
    5. Position Management
    """

    def __init__(
        self,
        config: TradingBotConfig,
        exchange: IExchange,
        database: DatabaseManager,
        messaging: Optional[MessagingClient] = None,
        paper_broker: Optional[PaperBroker] = None,
        run_id: str = "",
        strategy_config: Optional[Any] = None,  # Legacy single config
        strategy_configs: Optional[List[Any]] = None,  # List of configs
    ):
        self.config = config
        self.exchange = exchange
        self.database = database
        self.messaging = messaging
        self.paper_broker = paper_broker
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.mode = self.config.app_mode
        self.indicators = TechnicalIndicators()

        # Initialize components
        self.signal_generator = SignalGenerator(self.indicators)
        self.position_manager = PositionManager(self.indicators)
        self.risk_manager = RiskManager(
            self.config, self.config.trading.initial_capital
        )
        self.market_data_provider = MarketDataProvider(self.exchange)

        # Initialize Execution Engine
        from src.engine.execution import ExecutionEngine

        self.execution_engine = ExecutionEngine(
            config=self.config,
            exchange=self.exchange,
            database=self.database,
            messaging=self.messaging,
            position_manager=self.position_manager,
            risk_manager=self.risk_manager,
            run_id=self.run_id,
            mode=self.mode,
        )

        # State tracking
        self.positions: Dict[str, PositionSnapshot] = {}
        self.orders: Dict[str, OrderResponse] = {}

        if strategy_config:
            logger.info(f"Initializing Dynamic Strategy Engine: {strategy_config.name}")
            self.dynamic_engines[strategy_config.name] = DynamicStrategyEngine(
                strategy_config
            )

        if strategy_configs:
            for cfg in strategy_configs:
                logger.info(f"Initializing Dynamic Strategy Engine: {cfg.name}")
                self.dynamic_engines[cfg.name] = DynamicStrategyEngine(cfg)

        # Strategy state
        self.market_data: Dict[str, Dict[str, pd.DataFrame]] = {}
        self.active_positions: Dict[str, Position] = {}
        self.pending_orders: List[OrderResponse] = []
        self.crisis_mode = False
        self.consecutive_losses = 0
        # This is strictly related to state management

        self.risk_state = None
        self.processing_orders: set[str] = set()
        self.data_stale_block_active = False

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
        "Subscribe to execution reports from the messaging system."
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
        "Handle execution reports received from the messaging system."
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
                    achieved_vs_signal_bps=report.get("achieved_vs_signal_bps", 0.0),
                    latency_ms=report.get("latency_ms", 0.0),
                    maker=report.get("maker", False),
                    mode=self.mode,
                    run_id=self.run_id,
                    timestamp=datetime.fromisoformat(report["timestamp"]),
                    is_shadow=is_shadow,
                )
                await self.database.create_trade(trade)
                pnl = report.get("realized_pnl", 0.0)
                self.total_pnl += pnl
                self.risk_manager.update_trade_stats(pnl)
                order_status = "filled"
            else:
                order_status = "rejected"

            await self.database.update_order_status(
                report["order_id"], order_status, is_shadow
            )

        except Exception as e:
            logger.error(f"Error handling execution report: {e}")

    async def update_market_data(self):
        "Update market data for all symbols and timeframes."
        try:
            market_updates = []
            stale_detected = False

            for symbol in self.config.trading.symbols:
                if symbol not in self.market_data:
                    self.market_data[symbol] = {}

                signal_snapshot: Optional[MarketSnapshot] = None

                # Fetch data for each timeframe
                for (
                    tf_name,
                    timeframe,
                ) in self.config.data.timeframes.model_dump().items():
                    lookback = getattr(self.config.data.lookback_periods, tf_name, 100)

                    # Fetch OHLCV data
                    data = await self.exchange.get_historical_data(
                        symbol=symbol, timeframe=timeframe, limit=lookback
                    )

                    if data is not None and not data.empty:
                        if self._is_stale_market_data(data, timeframe):
                            stale_detected = True
                            logger.error(
                                "SAFETY_STALE_DATA: Blocking trading for %s due to stale %s data",
                                symbol,
                                timeframe,
                            )
                            continue
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
            self.data_stale_block_active = stale_detected

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
        "Run the trading analysis loop for all symbols."
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
            timestamp=datetime.now(timezone.utc),
        )
        return snapshot

    @staticmethod
    def _timeframe_to_timedelta(timeframe: str) -> Optional[pd.Timedelta]:
        value = timeframe.strip().lower()
        try:
            if value.endswith("m"):
                minutes = int(value[:-1])
                return pd.Timedelta(minutes=minutes)
            if value.endswith("h"):
                hours = int(value[:-1])
                return pd.Timedelta(hours=hours)
            if value.endswith("d"):
                days = int(value[:-1])
                return pd.Timedelta(days=days)
            minutes = int(value)
            return pd.Timedelta(minutes=minutes)
        except (ValueError, TypeError):
            return None

    def _is_stale_market_data(self, data: pd.DataFrame, timeframe: str) -> bool:
        if data.empty:
            return True
        delta = self._timeframe_to_timedelta(timeframe)
        if not delta:
            return False
        if "timestamp" in data.columns:
            last_ts = pd.to_datetime(data["timestamp"].iloc[-1], utc=True)
        else:
            last_ts = data.index[-1]
        now = pd.Timestamp.utcnow()
        staleness = now - last_ts
        if staleness > delta * 2:
            logger.warning(
                "SAFETY_STALE_DATA: %s data stale by %s", timeframe, staleness
            )
            return True
        if len(data) >= 2:
            gap = data.index[-1] - data.index[-2]
            if gap > delta * 2:
                logger.warning(
                    "SAFETY_DATA_GAP: %s gap %s exceeds expected %s",
                    timeframe,
                    gap,
                    delta,
                )
                return True
        return False

    def _generate_client_id(self, symbol: str) -> str:
        return (
            f"{self.run_id}-{symbol}-{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
        )

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

    @handle_exceptions(log_message="Error analyzing symbol")
    async def _analyze_symbol(self, symbol: str) -> None:
        "Analyze a single symbol for trading opportunities."

        logger.info(f"Analyzing {symbol}...")

        # 1. Fetch Market Data via Provider
        regime_data = await self.market_data_provider.get_ohlcv(
            symbol, "1d", limit=self.config.strategy.regime.ema_period + 100
        )
        setup_data = await self.market_data_provider.get_ohlcv(
            symbol, "4h", limit=self.config.strategy.setup.ema_slow + 50
        )
        signal_data = await self.market_data_provider.get_ohlcv(
            symbol, "1h", limit=self.config.strategy.signals.donchian_period + 50
        )

        if regime_data is None or setup_data is None or signal_data is None:
            logger.warning(f"Insufficient data for {symbol}")
            return

            # Microstructure Analysis (Common for all strategies)
            vwap_val: Optional[float] = None
            ob_metrics: Dict[str, Any] = {}

            if self.config.strategy.vwap.enabled:
                if self.config.strategy.vwap.mode == "rolling":
                    vwap_series = self.indicators.rolling_vwap(
                        signal_data, self.config.strategy.vwap.rolling_window
                    )
                else:
                    vwap_series = self.indicators.vwap(signal_data)
                vwap_val = vwap_series.iloc[-1]

            if self.config.strategy.orderbook.enabled:
                orderbook = await self.exchange.get_order_book(
                    symbol, limit=self.config.strategy.orderbook.depth
                )
                if orderbook:
                    ob_metrics["imbalance"] = (
                        OrderBookIndicators.compute_orderbook_imbalance(
                            orderbook, self.config.strategy.orderbook.depth
                        )
                    )
                    spread, mid, _ = OrderBookIndicators.compute_spread_and_mid(
                        orderbook
                    )
                    ob_metrics["spread"] = spread
                    ob_metrics["mid_price"] = mid
                    ob_metrics["walls"] = OrderBookIndicators.detect_liquidity_walls(
                        orderbook,
                        self.config.strategy.orderbook.depth,
                        self.config.strategy.orderbook.wall_multiplier,
                    )

            # Strategy Execution
            if self.dynamic_engines:
                # Run all dynamic strategies
                for name, engine in self.dynamic_engines.items():
                    # 1. Regime
                    regime = engine.detect_regime(regime_data)
                    # 2. Setup
                    setup = engine.detect_setup(setup_data)
                    # 3. Signals
                    signals = engine.generate_signals(signal_data)

                    # 4. Filter
                    # Note: Dynamic engine generate_signals checks entry conditions.
                    # But we might want to check regime/setup alignment.
                    # Use common filter logic.
                    # Actually, _filter_signals uses the `regime` and `setup` objects.
                    # So we can use it.

                    valid_signals = self.signal_generator.filter_signals(
                        signals, regime, setup
                    )

                    # 4.5 Microstructure
                    valid_signals = self.signal_generator.apply_microstructure_filters(
                        valid_signals, vwap_val, ob_metrics, self.config.strategy
                    )

                    # 5. Score and Execute
                    for signal in valid_signals:
                        confidence = engine.calculate_confidence(regime, setup, signal)
                        threshold = engine.config.confidence_threshold

                        if confidence.total_score >= threshold:
                            logger.info(
                                f"Strategy {name} triggered {signal.direction} "
                                f"signal for {symbol}"
                            )
                            await self._execute_signal(
                                symbol, signal, confidence, regime, vwap_val, ob_metrics
                            )

            else:
                # Component-based Strategy
                # 1. Regime Detection
                regime = self.signal_generator.detect_regime(
                    regime_data, self.config.strategy
                )

                # 2. Setup Detection
                setup = self.signal_generator.detect_setup(
                    setup_data, self.config.strategy
                )

                # 3. Signal Generation
                signals = self.signal_generator.generate_signals(
                    signal_data, self.config.strategy
                )

                # 4. Filter signals by regime and setup
                # Delegated to SignalGenerator
                valid_signals = self.signal_generator.filter_signals(
                    signals, regime, setup
                )

                # 4.5 Microstructure Analysis
                # Delegated to SignalGenerator
                valid_signals = self.signal_generator.apply_microstructure_filters(
                    valid_signals, vwap_val, ob_metrics, self.config.strategy
                )

                # 5. Score and execute valid signals
                for signal in valid_signals:
                    confidence = self.position_manager.calculate_confidence(
                        regime,
                        setup,
                        signal,
                        self.config.strategy,
                        self.market_data,
                        symbol,
                    )
                    threshold = self.config.strategy.confidence.min_threshold

                    if confidence.total_score >= threshold:
                        await self._execute_signal(
                            symbol, signal, confidence, regime, vwap_val, ob_metrics
                        )

    async def _execute_signal(
        self,
        symbol: str,
        signal: TradingSignal,
        confidence: ConfidenceScore,
        regime: MarketRegime,
        vwap_val: Optional[float] = None,
        ob_metrics: Optional[Dict[str, Any]] = None,
    ):
        "Delegate execution to ExecutionEngine."
        if symbol in self.processing_orders:
            logger.info(f"Signal ignored for {symbol}: Order processing in progress")
            return
        if self.data_stale_block_active:
            logger.warning(
                "SAFETY_STALE_DATA: Blocking signal execution for %s due to stale data",
                symbol,
            )
            return

        self.processing_orders.add(symbol)
        try:
            # Check if already have position in this symbol (Strategy level check)
            if symbol in self.active_positions:
                logger.info(f"Already have position in {symbol}, skipping signal")
                return

            # Check max positions
            if len(self.active_positions) >= self.config.trading.max_positions:
                logger.info(f"Max positions reached, skipping {symbol}")
                return

            current_equity = self.config.trading.initial_capital + self.total_pnl

            await self.execution_engine.execute_signal(
                symbol=symbol,
                signal=signal,
                confidence=confidence,
                regime=regime,
                current_equity=current_equity,
                initial_capital=self.config.trading.initial_capital,
                vwap_val=vwap_val,
                ob_metrics=ob_metrics,
            )

            # Update positions after execution
            await self.update_positions()

        except Exception as e:
            logger.error(f"Error executing signal for {symbol}: {e}")
        finally:
            self.processing_orders.discard(symbol)

    async def update_positions(self):
        "Update active positions."
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
                        updated_at=datetime.now(timezone.utc),
                    )

                self.active_positions[db_position.symbol] = db_position
                await self.database.update_position(db_position)

        except Exception as e:
            logger.error(f"Error updating positions: {e}")

    async def check_risk_management(self):
        "Check and enforce risk management rules."
        try:
            account_balance = self.config.trading.initial_capital + self.total_pnl

            # Delegate to RiskManager
            actions = await self.risk_manager.check_risk_management(
                current_equity=account_balance,
                active_positions_count=len(self.active_positions),
            )

            if actions.get("close_all"):
                await self.close_all_positions()

        except Exception as e:
            logger.error(f"Error checking risk management: {e}")

    async def close_all_positions(self):
        "Close all active positions."
        try:
            for symbol in list(self.active_positions.keys()):
                await self.exchange.close_position(symbol)
                logger.info(f"Closed position in {symbol}")

            self.active_positions.clear()

        except Exception as e:
            logger.error(f"Error closing positions: {e}")

    async def _subscribe_to_risk_updates(self):
        "Subscribe to risk management updates from the messaging system."
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
        "Wait for an execution result for a given order ID."
        # This is a placeholder. In a real implementation, this would
        # listen on a NATS subject for a response from the execution service.
        logger.info(f"Waiting for execution of order {order_id}")
        await asyncio.sleep(1)  # Simulate network latency
        return {"executed": True}

    async def _publish_performance_metrics(self):
        "Publish performance metrics to messaging system."
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
