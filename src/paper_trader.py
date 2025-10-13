"""
High-fidelity paper trading broker used in paper and replay modes.

The broker simulates fills with configurable latency, slippage, partial fills,
fees, funding accrual, and queue dynamics.  All events are persisted through
``DatabaseManager`` with idempotent keys and tagged with ``mode`` /
``run_id`` for downstream auditing.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple, cast

from .config import PaperConfig, RiskManagementConfig
from .database import DatabaseManager, Order, PnLEntry, Position, Trade
from .metrics import AVERAGE_SLIPPAGE_BPS, MAKER_RATIO, SIGNAL_ACK_LATENCY

Mode = Literal["live", "paper", "replay"]
Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_market"]


@dataclass
class MarketSnapshot:
    """Current observable market state used for simulation inputs."""

    symbol: str
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    last_price: float
    last_side: Optional[Side] = None
    last_size: float = 0.0
    funding_rate: float = 0.0  # hourly funding rate (positive -> longs pay)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    order_flow_imbalance: float = 0.0  # positive = buy pressure, negative = sell

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2.0
        return self.last_price

    @property
    def spread(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return max(self.best_ask - self.best_bid, 0.0)
        return 0.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid <= 0:
            return 0.0
        return (self.spread / mid) * 10_000


@dataclass
class _RestingOrder:
    order: Order
    limit_price: float
    remaining_qty: float
    reduce_only: bool = False


@dataclass
class _StopOrder:
    order: Order
    stop_price: float
    reduce_only: bool = True
    triggered: bool = False


@dataclass
class _PositionState:
    symbol: str
    size: float = 0.0  # positive = long, negative = short
    avg_price: float = 0.0
    unrealized_pnl: float = 0.0

    def update_mark(self, mark_price: float) -> None:
        if self.size == 0:
            self.unrealized_pnl = 0.0
            return
        direction = 1 if self.size > 0 else -1
        self.unrealized_pnl = (mark_price - self.avg_price) * self.size * direction


class PaperBroker:
    """
    Simulated broker responsible for order lifecycle in paper/replay modes.
    """

    def __init__(
        self,
        *,
        config: PaperConfig,
        database: DatabaseManager,
        mode: Mode,
        run_id: str,
        initial_balance: float,
        risk_config: Optional[RiskManagementConfig] = None,
        execution_listener: Optional[
            Callable[[Dict[str, Any]], Awaitable[None]]
        ] = None,
    ):
        self.config = config
        self.database = database
        self.mode = mode
        self.run_id = run_id
        self._balance = initial_balance
        self._execution_listener = execution_listener

        self._lock = asyncio.Lock()
        self._market_state: Dict[str, MarketSnapshot] = {}
        self._positions: Dict[str, _PositionState] = {}
        self._resting_limits: Dict[str, List[_RestingOrder]] = {}
        self._stop_orders: Dict[str, _StopOrder] = {}
        self._latency_mu = config.latency_ms.mean
        self._latency_sigma = self._derive_latency_sigma(
            config.latency_ms.mean, config.latency_ms.p95
        )
        self._order_progress: Dict[str, float] = {}
        self._random = random.Random(config.seed)
        self._max_leverage = max(float(config.max_leverage), 1.0)
        self._maintenance_margin_pct = max(float(config.maintenance_margin_pct), 0.0)
        self._initial_margin_pct = max(
            float(config.initial_margin_pct), self._maintenance_margin_pct
        )
        self._hard_stop_pct = (
            float(risk_config.stops.hard_risk_percent) if risk_config else 0.02
        )

        self._maker_fills = 0
        self._taker_fills = 0
        self._maker_fills_by_symbol: Dict[str, int] = defaultdict(int)
        self._taker_fills_by_symbol: Dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def place_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: float,
        *,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        reduce_only: bool = False,
        is_shadow: bool = False,
        client_id: Optional[str] = None,
    ) -> Order:
        """
        Submit an order into the paper broker.
        """

        if quantity <= 0:
            raise ValueError("quantity must be positive")

        async with self._lock:
            snapshot = self._market_state.get(symbol)
            if not snapshot:
                raise RuntimeError(f"No market data available for {symbol}")

            order_id = client_id or f"paper-{uuid.uuid4().hex[:12]}"
            order = Order(
                client_id=order_id,
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                status="open",
                mode=self.mode,
                run_id=self.run_id,
                is_shadow=is_shadow,
            )

            await self.database.create_order(order)
            self._order_progress[order.client_id] = order.quantity

            if order_type in ("stop", "stop_market"):
                if stop_price is None:
                    raise ValueError("stop orders must provide stop_price")
                self._stop_orders[order.client_id] = _StopOrder(
                    order=order, stop_price=stop_price, reduce_only=reduce_only
                )
                return order

            if order_type == "limit" and price is None:
                raise ValueError("limit orders must provide price")

            fills = self._simulate_order(snapshot, order, reduce_only=reduce_only)
            if fills:
                for delay_ms, fill_qty, fill_price, maker, slippage_bps in fills:
                    asyncio.create_task(
                        self._finalise_fill(
                            order=order,
                            snapshot=snapshot,
                            fill_qty=fill_qty,
                            fill_price=fill_price,
                            maker=maker,
                            slippage_bps=slippage_bps,
                            delay_ms=delay_ms,
                            reduce_only=reduce_only,
                        )
                    )
            else:
                # Resting limit order waiting for future fill
                self._resting_limits.setdefault(symbol, []).append(
                    _RestingOrder(
                        order=order,
                        limit_price=price if price is not None else 0.0,
                        remaining_qty=quantity,
                        reduce_only=reduce_only,
                    )
                )

            return order

    async def update_market(self, snapshot: MarketSnapshot) -> None:
        """
        Update the broker with the latest market snapshot.

        This drives mark-to-market calculation, stop triggers, and fills for
        resting limit orders.
        """

        triggers: List[_StopOrder] = []
        fills: List[Tuple[_RestingOrder, MarketSnapshot]] = []

        async with self._lock:
            previous = self._market_state.get(snapshot.symbol)
            snapshot.order_flow_imbalance = self._compute_order_flow(previous, snapshot)
            self._market_state[snapshot.symbol] = snapshot

            # Update marks
            position_state = self._positions.get(snapshot.symbol)
            if position_state:
                position_state.update_mark(snapshot.mid_price)
                await self.database.update_position(
                    Position(
                        symbol=snapshot.symbol,
                        side="long" if position_state.size >= 0 else "short",
                        size=abs(position_state.size),
                        entry_price=position_state.avg_price,
                        mark_price=snapshot.mid_price,
                        unrealized_pnl=position_state.unrealized_pnl,
                        percentage=self._position_return_pct(position_state),
                        mode=self.mode,
                        run_id=self.run_id,
                    )
                )

            # Stop triggers
            for key, stop in list(self._stop_orders.items()):
                if self._should_trigger_stop(stop, snapshot):
                    stop.triggered = True
                    triggers.append(stop)
                    del self._stop_orders[key]

            # Resting limit fills
            rest_list = self._resting_limits.get(snapshot.symbol, [])
            remaining_rest = []
            for rest in rest_list:
                if self._limit_crossed(rest, snapshot):
                    fills.append((rest, snapshot))
                else:
                    remaining_rest.append(rest)
            if remaining_rest:
                self._resting_limits[snapshot.symbol] = remaining_rest
            else:
                self._resting_limits.pop(snapshot.symbol, None)

        for stop in triggers:
            await self._execute_stop(stop, snapshot)

        for rest, snap in fills:
            await self._fill_resting_limit(rest, snap)

    async def get_positions(self) -> List[Position]:
        async with self._lock:
            return [
                Position(
                    symbol=symbol,
                    side="long" if state.size >= 0 else "short",
                    size=abs(state.size),
                    entry_price=state.avg_price,
                    mark_price=self._market_state.get(
                        symbol, MarketSnapshot(symbol, 0, 0, 0, 0, 0)
                    ).mid_price,
                    unrealized_pnl=state.unrealized_pnl,
                    percentage=self._position_return_pct(state),
                    mode=self.mode,
                    run_id=self.run_id,
                )
                for symbol, state in self._positions.items()
                if state.size != 0
            ]

    async def close_position(self, symbol: str) -> bool:
        async with self._lock:
            position = self._positions.get(symbol)
            snapshot = self._market_state.get(symbol)
            if not position or position.size == 0 or not snapshot:
                return False

            side: Side = "sell" if position.size > 0 else "buy"
            quantity = abs(position.size)

        await self.place_order(
            symbol=symbol,
            side=side,
            order_type="market",
            quantity=quantity,
            reduce_only=True,
        )
        return True

    async def get_account_balance(self) -> Dict[str, float]:
        async with self._lock:
            return {"totalWalletBalance": self._balance}

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _derive_latency_sigma(self, mean: float, p95: float) -> float:
        if p95 <= mean:
            return mean * 0.15 if mean > 0 else 1.0
        # Assuming normal distribution, z-score for 95th percentile ~1.645
        return max((p95 - mean) / 1.645, 1.0)

    def _sample_latency_ms(self) -> float:
        latency = self._random.gauss(self._latency_mu, self._latency_sigma)
        return max(latency, 0.0)

    def _compute_order_flow(
        self, previous: Optional[MarketSnapshot], current: MarketSnapshot
    ) -> float:
        if previous is None:
            base = 0.0
        else:
            base = previous.order_flow_imbalance * 0.85  # decay
        if current.last_side == "buy":
            base += current.last_size
        elif current.last_side == "sell":
            base -= current.last_size
        return base

    def _simulate_order(
        self,
        snapshot: MarketSnapshot,
        order: Order,
        *,
        reduce_only: bool,
    ) -> List[Tuple[float, float, float, bool, float]]:
        """
        Return a list of planned fills represented as tuples:
        (delay_ms, fill_qty, fill_price, maker, slippage_bps)
        """

        order_side: Side = cast(Side, order.side)

        if order.order_type == "market":
            slippage_bps = self._compute_slippage_bps(snapshot, order_side)
            price = self._apply_slippage(snapshot, order_side, slippage_bps)
            return [
                (
                    self._sample_latency_ms(),
                    order.quantity,
                    price,
                    False,
                    slippage_bps,
                )
            ]

        if order.order_type == "limit":
            if order.price is None:
                raise ValueError("limit order missing price")

            if self._limit_crosses_spread(order_side, order.price, snapshot):
                slippage_bps = self._compute_slippage_bps(snapshot, order_side)
                price = self._apply_slippage(snapshot, order_side, slippage_bps)
                return [
                    (
                        self._sample_latency_ms(),
                        order.quantity,
                        price,
                        False,
                        slippage_bps,
                    )
                ]

            # Resting on the book as maker
            slice_plan = self._build_partial_fill_plan(order.quantity)
            fills: List[Tuple[float, float, float, bool, float]] = []
            base_price = order.price
            for index, qty in enumerate(slice_plan):
                jitter = 1.0 + index / max(len(slice_plan), 1)
                delay = self._sample_latency_ms() * jitter
                fills.append((delay, qty, base_price, True, 0.0))
            return fills

        return []

    def _limit_crosses_spread(
        self, side: Side, price: float, snapshot: MarketSnapshot
    ) -> bool:
        if side == "buy":
            if snapshot.best_ask > 0 and price >= snapshot.best_ask:
                return True
            if snapshot.last_price and price >= snapshot.last_price:
                return True
        else:
            if snapshot.best_bid > 0 and price <= snapshot.best_bid:
                return True
            if snapshot.last_price and price <= snapshot.last_price:
                return True
        return False

    def _compute_slippage_bps(self, snapshot: MarketSnapshot, side: Side) -> float:
        spread_term = snapshot.spread_bps * self.config.spread_slippage_coeff
        ofi = snapshot.order_flow_imbalance
        adverse_flow = max(0.0, -ofi) if side == "buy" else max(0.0, ofi)
        # normalise adverse flow to bps using total depth
        depth = max(snapshot.bid_size + snapshot.ask_size, 1.0)
        adverse_bps = (adverse_flow / depth) * 10_000
        slippage = (
            self.config.slippage_bps
            + spread_term
            + adverse_bps * self.config.ofi_slippage_coeff
        )
        return min(slippage, self.config.max_slippage_bps)

    def _apply_slippage(
        self, snapshot: MarketSnapshot, side: Side, slippage_bps: float
    ) -> float:
        base_price = (
            snapshot.best_ask
            if side == "buy" and snapshot.best_ask > 0
            else snapshot.best_bid
        )
        if base_price <= 0:
            base_price = snapshot.mid_price
        if base_price <= 0:
            base_price = snapshot.last_price
        if base_price <= 0:
            raise RuntimeError(
                "Unable to determine base price for slippage computation"
            )

        multiplier = slippage_bps / 10_000
        if side == "buy":
            return base_price * (1 + multiplier)
        return base_price * (1 - multiplier)

    def _build_partial_fill_plan(self, quantity: float) -> List[float]:
        if not self.config.partial_fill.enabled or quantity <= 0:
            return [quantity]

        slices = min(
            max(1, self._random.randint(1, self.config.partial_fill.max_slices)),
            self.config.partial_fill.max_slices,
        )
        plan: List[float] = []
        remaining = quantity
        min_slice = quantity * self.config.partial_fill.min_slice_pct

        for idx in range(1, slices):
            max_remaining = remaining - min_slice * (slices - idx)
            if max_remaining <= min_slice:
                qty = min_slice
            else:
                qty = self._random.uniform(min_slice, max_remaining)
            qty = min(qty, remaining)
            plan.append(qty)
            remaining -= qty

        plan.append(max(remaining, 0.0))
        return [qty for qty in plan if qty > 0]

    async def _finalise_fill(
        self,
        *,
        order: Order,
        snapshot: MarketSnapshot,
        fill_qty: float,
        fill_price: float,
        maker: bool,
        slippage_bps: float,
        delay_ms: float,
        reduce_only: bool,
    ) -> None:
        await asyncio.sleep(delay_ms / 1000.0)

        fee_rate_bps = self.config.maker_rebate_bps if maker else self.config.fee_bps
        fee_amount = fill_price * fill_qty * fee_rate_bps / 10_000

        execution_report: Optional[Dict[str, Any]] = None

        async with self._lock:
            try:
                position_state = self._positions.setdefault(
                    order.symbol, _PositionState(symbol=order.symbol)
                )

                realized_pnl, updated_size, updated_price = self._apply_position_fill(
                    position_state, cast(Side, order.side), fill_qty, fill_price
                )
                position_state.size = updated_size
                position_state.avg_price = updated_price

                mark_price = snapshot.mid_price
                position_state.update_mark(mark_price)
                if not reduce_only:
                    self._enforce_liquidation_buffer(
                        position_state,
                        stop_price=order.stop_price,
                        side=cast(Side, order.side),
                    )

                funding = self._compute_funding(fill_price, fill_qty, snapshot)
                net_cash = realized_pnl - fee_amount - funding
                self._balance += net_cash

                trade = Trade(
                    client_id=f"{order.client_id}-{uuid.uuid4().hex[:6]}",
                    trade_id=f"{order.order_id}-{uuid.uuid4().hex[:6]}",
                    order_id=order.order_id or order.client_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=fill_qty,
                    price=fill_price,
                    commission=0.0,
                    fees=fee_amount,
                    funding=funding,
                    realized_pnl=realized_pnl,
                    mark_price=mark_price,
                    slippage_bps=slippage_bps,
                    latency_ms=delay_ms,
                    maker=maker,
                    mode=self.mode,
                    run_id=self.run_id,
                    timestamp=datetime.utcnow(),
                    is_shadow=order.is_shadow,
                )
                await self.database.create_trade(trade)

                await self.database.add_pnl_entry(
                    PnLEntry(
                        symbol=order.symbol,
                        trade_id=trade.trade_id,
                        realized_pnl=realized_pnl,
                        unrealized_pnl=position_state.unrealized_pnl,
                        commission=trade.commission,
                        fees=fee_amount,
                        funding=funding,
                        net_pnl=net_cash,
                        balance=self._balance,
                        mode=self.mode,
                        run_id=self.run_id,
                        timestamp=trade.timestamp,
                    )
                )

                remaining = max(
                    self._order_progress.get(order.client_id, 0.0) - fill_qty, 0.0
                )
                self._order_progress[order.client_id] = remaining
                status = "filled" if remaining <= 1e-8 else "partially_filled"
                await self.database.update_order_status(
                    order_id=order.order_id or order.client_id,
                    status=status,
                    is_shadow=order.is_shadow,
                )
                if status == "filled":
                    self._order_progress.pop(order.client_id, None)

                SIGNAL_ACK_LATENCY.labels(mode=self.mode).observe(delay_ms / 1000.0)
                AVERAGE_SLIPPAGE_BPS.labels(mode=self.mode, symbol=order.symbol).set(
                    slippage_bps
                )
                if maker:
                    self._maker_fills += 1
                    self._maker_fills_by_symbol[order.symbol] += 1
                else:
                    self._taker_fills += 1
                    self._taker_fills_by_symbol[order.symbol] += 1
                total_symbol_fills = (
                    self._maker_fills_by_symbol[order.symbol]
                    + self._taker_fills_by_symbol[order.symbol]
                )
                if total_symbol_fills > 0:
                    MAKER_RATIO.labels(mode=self.mode, symbol=order.symbol).set(
                        self._maker_fills_by_symbol[order.symbol] / total_symbol_fills
                    )

                execution_report = {
                    "order_id": order.order_id or order.client_id,
                    "client_id": order.client_id,
                    "symbol": order.symbol,
                    "executed": True,
                    "price": fill_price,
                    "mark_price": mark_price,
                    "quantity": fill_qty,
                    "fees": fee_amount,
                    "funding": funding,
                    "realized_pnl": realized_pnl,
                    "slippage_bps": slippage_bps,
                    "maker": maker,
                    "latency_ms": delay_ms,
                    "ack_latency_ms": delay_ms,
                    "mode": self.mode,
                    "run_id": self.run_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "is_shadow": order.is_shadow,
                    "error": "",
                    "reduce_only": reduce_only,
                    "order_type": order.order_type,
                    "stop_price": order.stop_price,
                    "initial_price": order.price,
                }
            except RuntimeError as exc:
                logger = logging.getLogger(__name__)
                logger.warning(
                    "Order %s rejected by liquidation guard: %s", order.client_id, exc
                )
                self._order_progress.pop(order.client_id, None)
                await self.database.update_order_status(
                    order_id=order.order_id or order.client_id,
                    status="rejected",
                    is_shadow=order.is_shadow,
                )
                execution_report = {
                    "order_id": order.order_id or order.client_id,
                    "client_id": order.client_id,
                    "symbol": order.symbol,
                    "executed": False,
                    "price": None,
                    "mark_price": snapshot.mid_price,
                    "quantity": 0.0,
                    "fees": 0.0,
                    "funding": 0.0,
                    "realized_pnl": 0.0,
                    "slippage_bps": 0.0,
                    "maker": False,
                    "latency_ms": delay_ms,
                    "ack_latency_ms": delay_ms,
                    "mode": self.mode,
                    "run_id": self.run_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "is_shadow": order.is_shadow,
                    "error": str(exc),
                    "reduce_only": reduce_only,
                    "order_type": order.order_type,
                    "stop_price": order.stop_price,
                    "initial_price": order.price,
                }

        if execution_report and self._execution_listener:
            try:
                await self._execution_listener(execution_report)
            except Exception:
                logger = logging.getLogger(__name__)
                logger.exception("Execution listener failed")

    async def _execute_stop(self, stop: _StopOrder, snapshot: MarketSnapshot) -> None:
        market_order = stop.order
        await self.place_order(
            symbol=market_order.symbol,
            side=cast(Side, market_order.side),
            order_type="market",
            quantity=market_order.quantity,
            reduce_only=stop.reduce_only,
            is_shadow=market_order.is_shadow,
            client_id=market_order.client_id,
        )

    async def _fill_resting_limit(
        self, rest: _RestingOrder, snapshot: MarketSnapshot
    ) -> None:
        fills = self._simulate_order(
            snapshot,
            rest.order,
            reduce_only=rest.reduce_only,
        )
        for delay_ms, qty, price, maker, slippage_bps in fills:
            asyncio.create_task(
                self._finalise_fill(
                    order=rest.order,
                    snapshot=snapshot,
                    fill_qty=qty,
                    fill_price=price,
                    maker=maker,
                    slippage_bps=slippage_bps,
                    delay_ms=delay_ms,
                    reduce_only=rest.reduce_only,
                )
            )

    def _should_trigger_stop(self, stop: _StopOrder, snapshot: MarketSnapshot) -> bool:
        mid = snapshot.mid_price
        if mid <= 0:
            return False
        side = cast(Side, stop.order.side)
        if side == "sell":
            return mid <= stop.stop_price
        return mid >= stop.stop_price

    def _limit_crossed(self, rest: _RestingOrder, snapshot: MarketSnapshot) -> bool:
        side = cast(Side, rest.order.side)
        return self._limit_crosses_spread(side, rest.limit_price, snapshot)

    def _apply_position_fill(
        self,
        position: _PositionState,
        side: Side,
        quantity: float,
        price: float,
    ) -> Tuple[float, float, float]:
        """Return realized PnL, new size, new average price."""

        size = position.size
        realized = 0.0
        direction = 1 if side == "buy" else -1

        if size == 0 or size * direction >= 0:
            # Increasing exposure in same direction
            new_size = size + direction * quantity
            total_abs = abs(size) + quantity
            new_avg = (
                (position.avg_price * abs(size) + price * quantity) / total_abs
                if total_abs > 0
                else price
            )
            return realized, new_size, new_avg

        # Reducing or flipping
        closing_qty = min(abs(size), quantity)
        if size > 0:
            realized += (price - position.avg_price) * closing_qty
        else:
            realized += (position.avg_price - price) * closing_qty

        remaining = abs(size) - closing_qty
        if remaining > 0:
            new_size = math.copysign(remaining, size)
            new_avg = position.avg_price
        else:
            leftover = quantity - closing_qty
            if leftover > 0:
                new_size = direction * leftover
                new_avg = price
            else:
                new_size = 0.0
                new_avg = 0.0

        return realized, new_size, new_avg

    def _position_return_pct(self, position: _PositionState) -> float:
        if position.size == 0 or position.avg_price == 0:
            return 0.0
        return (
            position.unrealized_pnl / (abs(position.size) * position.avg_price)
        ) * 100

    def _compute_funding(
        self, price: float, quantity: float, snapshot: MarketSnapshot
    ) -> float:
        if not self.config.funding_enabled or snapshot.funding_rate == 0:
            return 0.0
        notional = price * quantity
        # funding applied on hourly basis relative to snapshot timestamp
        hours = 1.0
        return notional * snapshot.funding_rate * hours

    def _derive_stop_distance(
        self, avg_price: float, stop_price: Optional[float], direction: int
    ) -> float:
        if avg_price <= 0:
            return 0.0
        if stop_price is not None:
            return max(abs(avg_price - stop_price), 0.0)
        return max(avg_price * self._hard_stop_pct, 0.0)

    def _estimate_liquidation_price(self, avg_price: float, direction: int) -> float:
        if avg_price <= 0:
            return avg_price
        leverage_buffer = 1.0 / self._max_leverage
        initial = max(self._initial_margin_pct, leverage_buffer)
        maintenance = self._maintenance_margin_pct
        buffer = initial - maintenance
        if buffer <= 0:
            buffer = leverage_buffer * 0.5
        buffer = min(buffer, 0.9)
        if direction >= 0:
            return avg_price * (1 - buffer)
        return avg_price * (1 + buffer)

    def _enforce_liquidation_buffer(
        self,
        position: _PositionState,
        *,
        stop_price: Optional[float],
        side: Side,
    ) -> None:
        if position.size == 0 or position.avg_price <= 0:
            return
        direction = 1 if position.size > 0 else -1
        stop_distance = self._derive_stop_distance(
            position.avg_price, stop_price, direction
        )
        if stop_distance <= 0:
            return
        liq_price = self._estimate_liquidation_price(position.avg_price, direction)
        liq_distance = abs(position.avg_price - liq_price)
        if liq_distance < stop_distance * 4:
            raise RuntimeError(
                (
                    "Liquidation buffer breached: liq_distance=%.4f stop_distance=%.4f "
                    "required=%.4f direction=%s"
                )
                % (
                    liq_distance,
                    stop_distance,
                    stop_distance * 4,
                    side,
                )
            )
