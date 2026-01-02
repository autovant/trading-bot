import asyncio
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import polars as pl
from pydantic import BaseModel, Field

from src.domain.entities import (
    MarketData,
    Order,
    OrderStatus,
    Position,
    Side,
    Trade,
)
from src.domain.interfaces import IExecutionEngine, IStrategy

logger = logging.getLogger(__name__)

TIMEFRAME_PERIODS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class BacktestConfig(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "1m"
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    initial_capital: float = Field(default=100_000.0, gt=0)
    slippage: float = Field(default=0.0003, ge=0.0)
    fee: float = Field(default=0.0004, ge=0.0)
    spread_bps: float = Field(default=2.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    funding_rate: float = Field(default=0.0)
    funding_interval_hours: int = Field(default=8, ge=1)
    maintenance_margin_pct: float = Field(default=0.005, ge=0.0)
    partial_fill_enabled: bool = True
    partial_fill_min_slice_pct: float = Field(default=0.2, ge=0.0, le=1.0)
    partial_fill_max_slices: int = Field(default=4, ge=1)
    risk_free_rate: float = 0.02  # annual
    mode: str = "event"  # "event" | "vectorized"


class BacktestMetrics(BaseModel):
    total_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    profit_factor: float
    win_rate: float
    calmar_ratio: float
    trades: int


class BacktestResult(BaseModel):
    equity_curve: List[Dict[str, float]]
    metrics: BacktestMetrics
    trades: List[Trade]


class BacktestExecutionEngine(IExecutionEngine):
    """Simulated execution engine for backtesting."""

    def __init__(
        self,
        initial_capital: float,
        slippage: float,
        fee: float,
        *,
        spread_bps: float,
        latency_ms: int,
        funding_rate: float,
        funding_interval_hours: int,
        maintenance_margin_pct: float,
        partial_fill_enabled: bool,
        partial_fill_min_slice_pct: float,
        partial_fill_max_slices: int,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.slippage = slippage
        self.fee = fee
        self.spread_bps = spread_bps
        self.latency_ms = latency_ms
        self.funding_rate = funding_rate
        self.funding_interval_hours = funding_interval_hours
        self.maintenance_margin_pct = maintenance_margin_pct
        self.partial_fill_enabled = partial_fill_enabled
        self.partial_fill_min_slice_pct = partial_fill_min_slice_pct
        self.partial_fill_max_slices = partial_fill_max_slices
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.orders: Dict[str, Order] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.trade_pnls: List[float] = []
        self.current_time: datetime = datetime.now(timezone.utc)
        self._last_funding_time: Optional[datetime] = None

    async def submit_order(self, order: Order) -> Order:
        price = order.price or order.metadata.get("tick_price")
        if price is None:
            raise ValueError("Order missing price for backtest fill")

        fill_price = self._apply_fill_price(float(price), order.side)
        slices = self._split_quantity(order.quantity)
        for idx, slice_qty in enumerate(slices):
            fee_cost = fill_price * slice_qty * self.fee
            self.cash -= fee_cost

            if order.side == Side.BUY:
                self.cash -= fill_price * slice_qty
            else:
                self.cash += fill_price * slice_qty

            trade = Trade(
                id=str(uuid.uuid4()),
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                quantity=slice_qty,
                price=fill_price,
                commission=fee_cost,
                timestamp=self._fill_timestamp(idx),
            )
            self.trades.append(trade)
            self.orders[order.id] = order

            existing = self.positions.get(order.symbol)
            if existing is None:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    side=order.side,
                    quantity=slice_qty,
                    entry_price=fill_price,
                    current_price=fill_price,
                )
            else:
                if existing.side == order.side:
                    new_qty = existing.quantity + slice_qty
                    weighted_entry = (
                        existing.entry_price * existing.quantity
                        + fill_price * slice_qty
                    ) / new_qty
                    existing.entry_price = weighted_entry
                    existing.quantity = new_qty
                    existing.current_price = fill_price
                else:
                    close_qty = min(existing.quantity, slice_qty)
                    realized = self._realized_pnl(
                        existing.side, existing.entry_price, fill_price, close_qty
                    )
                    self.trade_pnls.append(realized)
                    existing.quantity -= close_qty

                    if existing.quantity <= 0:
                        del self.positions[order.symbol]

                    remaining = slice_qty - close_qty
                    if remaining > 0:
                        self.positions[order.symbol] = Position(
                            symbol=order.symbol,
                            side=order.side,
                            quantity=remaining,
                            entry_price=fill_price,
                            current_price=fill_price,
                        )

        order.status = OrderStatus.FILLED
        return order

    async def cancel_order(self, order_id: str):
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELED

    async def get_positions(self) -> List[Position]:
        return list(self.positions.values())

    def mark_to_market(self, price_map: Dict[str, float], timestamp: datetime) -> float:
        equity = self.cash
        for symbol, pos in list(self.positions.items()):
            if symbol not in price_map:
                continue
            pos.current_price = price_map[symbol]
            direction = 1 if pos.side == Side.BUY else -1
            pos.unrealized_pnl = direction * (
                (pos.current_price - pos.entry_price) * pos.quantity
            )
            equity += pos.unrealized_pnl
        self._apply_funding(timestamp)
        equity = self.cash + sum(
            pos.unrealized_pnl for pos in self.positions.values()
        )
        equity = self._check_liquidation(equity, timestamp)
        self.equity_curve.append((timestamp, equity))
        self.current_time = timestamp
        return equity

    def _apply_spread(self, price: float, side: Side) -> float:
        if self.spread_bps <= 0:
            return price
        spread = price * (self.spread_bps / 10000)
        return price + (spread / 2) if side == Side.BUY else price - (spread / 2)

    def _apply_slippage(self, price: float, side: Side) -> float:
        return price * (1 + self.slippage if side == Side.BUY else 1 - self.slippage)

    def _apply_fill_price(self, price: float, side: Side) -> float:
        return self._apply_slippage(self._apply_spread(price, side), side)

    def _split_quantity(self, quantity: float) -> List[float]:
        if not self.partial_fill_enabled or self.partial_fill_max_slices <= 1:
            return [quantity]
        max_slices = max(1, self.partial_fill_max_slices)
        min_pct = max(self.partial_fill_min_slice_pct, 0.0001)
        max_by_min = max(1, int(1 / min_pct))
        slices = min(max_slices, max_by_min)
        base_qty = quantity / slices
        result = [base_qty for _ in range(slices)]
        result[-1] = quantity - base_qty * (slices - 1)
        return result

    def _fill_timestamp(self, slice_index: int) -> datetime:
        if self.latency_ms <= 0:
            return self.current_time
        return self.current_time + timedelta(milliseconds=self.latency_ms * (slice_index + 1))

    def _apply_funding(self, timestamp: datetime) -> None:
        if self.funding_rate == 0:
            self._last_funding_time = timestamp
            return
        if self._last_funding_time is None:
            self._last_funding_time = timestamp
            return
        delta_seconds = (timestamp - self._last_funding_time).total_seconds()
        if delta_seconds <= 0:
            return
        interval_seconds = self.funding_interval_hours * 3600
        rate_per_second = self.funding_rate / interval_seconds
        for pos in self.positions.values():
            notional = pos.current_price * pos.quantity
            funding_cost = notional * rate_per_second * delta_seconds
            if pos.side == Side.BUY:
                self.cash -= funding_cost
            else:
                self.cash += funding_cost
        self._last_funding_time = timestamp

    def _check_liquidation(self, equity: float, timestamp: datetime) -> float:
        if not self.positions:
            return equity
        total_notional = sum(
            pos.current_price * pos.quantity for pos in self.positions.values()
        )
        maintenance = total_notional * self.maintenance_margin_pct
        if total_notional > 0 and equity <= maintenance:
            self._liquidate_positions(timestamp)
            return self.cash
        return equity

    def _liquidate_positions(self, timestamp: datetime) -> None:
        for symbol, pos in list(self.positions.items()):
            closing_side = Side.SELL if pos.side == Side.BUY else Side.BUY
            notional = pos.current_price * pos.quantity
            fee_cost = notional * self.fee
            self.cash -= fee_cost
            if closing_side == Side.SELL:
                self.cash += notional
            else:
                self.cash -= notional
            self.trades.append(
                Trade(
                    id=str(uuid.uuid4()),
                    order_id="liquidation",
                    symbol=symbol,
                    side=closing_side,
                    quantity=pos.quantity,
                    price=pos.current_price,
                    commission=fee_cost,
                    timestamp=timestamp,
                )
            )
            del self.positions[symbol]

    def _realized_pnl(
        self, side: Side, entry: float, exit_price: float, qty: float
    ) -> float:
        if side == Side.BUY:
            return (exit_price - entry) * qty
        return (entry - exit_price) * qty


class BacktestEngine:
    """Event-driven + vectorized backtester built on Polars."""

    def __init__(
        self,
        strategy: IStrategy,
        data: pl.DataFrame,
        config: Optional[BacktestConfig] = None,
    ):
        if data.is_empty():
            raise ValueError("Backtest data is empty")
        self.strategy = strategy
        self.data = data
        self.config = config or BacktestConfig()
        self.execution_engine = BacktestExecutionEngine(
            initial_capital=self.config.initial_capital,
            slippage=self.config.slippage,
            fee=self.config.fee,
            spread_bps=self.config.spread_bps,
            latency_ms=self.config.latency_ms,
            funding_rate=self.config.funding_rate,
            funding_interval_hours=self.config.funding_interval_hours,
            maintenance_margin_pct=self.config.maintenance_margin_pct,
            partial_fill_enabled=self.config.partial_fill_enabled,
            partial_fill_min_slice_pct=self.config.partial_fill_min_slice_pct,
            partial_fill_max_slices=self.config.partial_fill_max_slices,
        )

    async def run_event_driven(self) -> BacktestResult:
        logger.info("Starting Event-Driven Backtest...")
        df = self._filtered_data()

        for row in df.iter_rows(named=True):
            market_data = MarketData(
                symbol=row.get("symbol", self.config.symbol),
                timestamp=row["timestamp"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row.get("volume", 0.0),
            )

            self.execution_engine.current_time = market_data.timestamp
            orders = await self.strategy.on_tick(market_data) or []
            for order in orders:
                order.metadata.setdefault("tick_price", market_data.close)
                await self.execution_engine.submit_order(order)

            self.execution_engine.mark_to_market(
                {market_data.symbol: market_data.close}, market_data.timestamp
            )

        return self._finalize_result()

    def run_vectorized(self) -> BacktestResult:
        logger.info("Starting Vectorized Backtest...")
        df = self._filtered_data()
        signals_df = self.strategy.vectorized_signals(df)

        if signals_df is None or "signal" not in signals_df.columns:
            logger.info(
                "Strategy does not implement vectorized_signals; falling back to event-driven run."
            )
            return asyncio.get_event_loop().run_until_complete(self.run_event_driven())

        merged = df.join(
            signals_df.select(["timestamp", "signal"]), on="timestamp", how="left"
        )
        merged = merged.with_columns(
            pl.col("signal").fill_null(strategy="backward").fill_null(0).alias("signal")
        )
        merged = merged.with_columns(
            pl.col("close").pct_change().fill_null(0.0).alias("returns")
        )
        merged = merged.with_columns(
            (pl.col("returns") * pl.col("signal").shift(1).fill_null(0.0)).alias(
                "strategy_returns"
            )
        )
        merged = merged.with_columns(
            (
                (1 + pl.col("strategy_returns")).cum_prod()
                * self.config.initial_capital
            ).alias("equity")
        )

        equity_curve = list(zip(merged["timestamp"], merged["equity"], strict=False))
        trade_returns = self._extract_trade_returns(
            merged["signal"].to_list(), merged["returns"].to_list()
        )

        self.execution_engine.equity_curve = equity_curve
        metrics = self._calculate_metrics(
            equity_curve,
            trade_returns,
            merged["strategy_returns"].to_list(),
            self.config.timeframe,
        )

        return BacktestResult(
            equity_curve=self._equity_curve_to_dict(equity_curve),
            metrics=metrics,
            trades=self.execution_engine.trades,
        )

    def _filtered_data(self) -> pl.DataFrame:
        df = self.data
        if "timestamp" not in df.columns:
            raise ValueError("DataFrame missing 'timestamp' column for backtest")
        df = df.sort("timestamp")
        if self.config.start:
            df = df.filter(pl.col("timestamp") >= self.config.start)
        if self.config.end:
            df = df.filter(pl.col("timestamp") <= self.config.end)
        return df

    def _finalize_result(self) -> BacktestResult:
        metrics = self._calculate_metrics(
            self.execution_engine.equity_curve,
            self.execution_engine.trade_pnls,
            self._equity_returns_from_curve(self.execution_engine.equity_curve),
            self.config.timeframe,
        )
        return BacktestResult(
            equity_curve=self._equity_curve_to_dict(self.execution_engine.equity_curve),
            metrics=metrics,
            trades=self.execution_engine.trades,
        )

    def _calculate_metrics(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trade_pnls: List[float],
        returns: List[float],
        timeframe: str,
    ) -> BacktestMetrics:
        if not equity_curve:
            raise ValueError("Empty equity curve; backtest did not run")

        equity = np.array([eq for _, eq in equity_curve], dtype=float)
        total_return = (equity[-1] / equity[0]) - 1.0

        periods_per_year = max(
            1, math.floor(31536000 / TIMEFRAME_PERIODS.get(timeframe, 3600))
        )
        rf_per_period = self.config.risk_free_rate / periods_per_year

        returns_arr = np.array(returns, dtype=float)
        excess_returns = returns_arr - rf_per_period
        sharpe = 0.0
        if excess_returns.std(ddof=1) > 0:
            sharpe = (excess_returns.mean() / excess_returns.std(ddof=1)) * math.sqrt(
                periods_per_year
            )

        downside = excess_returns[excess_returns < 0]
        sortino = 0.0
        if downside.std(ddof=1) > 0:
            sortino = (excess_returns.mean() / downside.std(ddof=1)) * math.sqrt(
                periods_per_year
            )

        max_dd = self._max_drawdown(equity)

        positive = [p for p in trade_pnls if p > 0]
        negative = [p for p in trade_pnls if p < 0]
        gross_profit = sum(positive)
        gross_loss = abs(sum(negative)) if negative else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        wins = len(positive)
        losses = len(negative)
        win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.0

        calmar = (
            (total_return * periods_per_year) / max_dd if max_dd != 0 else float("inf")
        )

        return BacktestMetrics(
            total_return=total_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd,
            profit_factor=profit_factor,
            win_rate=win_rate,
            calmar_ratio=calmar,
            trades=len(trade_pnls),
        )

    def _max_drawdown(self, equity: np.ndarray) -> float:
        running_max = np.maximum.accumulate(equity)
        drawdowns = (equity - running_max) / running_max
        return float(abs(drawdowns.min()))

    def _equity_returns_from_curve(
        self, equity_curve: List[Tuple[datetime, float]]
    ) -> List[float]:
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1][1]
            curr = equity_curve[i][1]
            returns.append((curr - prev) / prev if prev != 0 else 0.0)
        return returns

    def _equity_curve_to_dict(
        self, equity_curve: List[Tuple[datetime, float]]
    ) -> List[Dict[str, float]]:
        return [
            {"timestamp": ts.timestamp(), "equity": float(eq)}
            for ts, eq in equity_curve
        ]

    def _extract_trade_returns(
        self, signals: List[float], returns: List[float]
    ) -> List[float]:
        if not signals or not returns:
            return []
        trade_returns: List[float] = []
        prev_signal = 0.0
        acc = 0.0
        for sig, ret in zip(signals, returns, strict=False):
            acc += ret * prev_signal
            if sig != prev_signal:
                if acc != 0:
                    trade_returns.append(acc)
                acc = 0.0
            prev_signal = sig
        if acc != 0:
            trade_returns.append(acc)
        return trade_returns
