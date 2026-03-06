"""
Mini Backtest Engine — lightweight in-memory backtest for parameter validation.

Used by the self-learning loop to quickly test candidate parameter sets
against recent market data before applying them to the live strategy.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..domain.entities import MarketData
from ..strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)


@dataclass
class MiniBacktestResult:
    """Result of a mini-backtest run."""

    sharpe: float = 0.0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_trades: int = 0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    avg_pnl_per_trade: float = 0.0
    wins: int = 0
    losses: int = 0
    trade_pnls: List[float] = field(default_factory=list)


async def run_mini_backtest(
    strategy_name: str,
    symbol: str,
    params: Dict[str, Any],
    market_data: List[Dict[str, Any]],
    position_size_usd: float = 100.0,
) -> MiniBacktestResult:
    """Run a fast backtest using recent market data in memory.

    Args:
        strategy_name: Registry key for the strategy preset.
        symbol: Trading pair symbol.
        params: Strategy parameters to test.
        market_data: List of OHLCV dicts with keys: open, high, low, close, volume, timestamp.
        position_size_usd: Notional size per trade.

    Returns:
        MiniBacktestResult with performance metrics.
    """
    result = MiniBacktestResult()

    if len(market_data) < 10:
        logger.warning("Mini-backtest: insufficient data (%d bars)", len(market_data))
        return result

    try:
        strategy = StrategyRegistry.instantiate(strategy_name, symbol, params)
    except (ValueError, KeyError) as e:
        logger.error("Mini-backtest: failed to instantiate strategy %s: %s", strategy_name, e)
        return result

    # Simulate trades
    open_trade: Optional[Dict[str, Any]] = None
    trade_pnls: List[float] = []

    for bar in market_data:
        ts = bar.get("timestamp", datetime.now(timezone.utc))
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                ts = datetime.now(timezone.utc)

        md = MarketData(
            symbol=symbol,
            timestamp=ts,
            open=float(bar.get("open", bar["close"])),
            high=float(bar.get("high", bar["close"])),
            low=float(bar.get("low", bar["close"])),
            close=float(bar["close"]),
            volume=float(bar.get("volume", 0)),
        )

        try:
            orders = await strategy.on_tick(md)
        except Exception as e:
            logger.debug("Mini-backtest on_tick error: %s", e)
            continue

        if not orders:
            continue

        for order in orders:
            price = order.price or md.close
            side = order.side.value if hasattr(order.side, "value") else str(order.side)

            if open_trade is None:
                # Open a new trade
                open_trade = {
                    "side": side,
                    "entry_price": price,
                    "quantity": position_size_usd / price if price > 0 else 0,
                    "timestamp": ts,
                }
            else:
                # Close existing trade
                entry = open_trade["entry_price"]
                qty = open_trade["quantity"]
                if open_trade["side"] == "buy":
                    pnl = (price - entry) * qty
                else:
                    pnl = (entry - price) * qty

                trade_pnls.append(pnl)
                open_trade = None

                # If this order also opens a new position in the opposite direction
                # (common in mean-reversion strategies)
                if side != open_trade["side"] if open_trade else True:
                    pass  # Position is now flat

    # Force-close any open trade at last price
    if open_trade and market_data:
        last_price = float(market_data[-1]["close"])
        entry = open_trade["entry_price"]
        qty = open_trade["quantity"]
        if open_trade["side"] == "buy":
            pnl = (last_price - entry) * qty
        else:
            pnl = (entry - last_price) * qty
        trade_pnls.append(pnl)

    # Compute metrics
    result.trade_pnls = trade_pnls
    result.total_trades = len(trade_pnls)

    if result.total_trades == 0:
        return result

    result.total_pnl = sum(trade_pnls)
    result.wins = sum(1 for p in trade_pnls if p > 0)
    result.losses = sum(1 for p in trade_pnls if p <= 0)
    result.win_rate = result.wins / result.total_trades
    result.avg_pnl_per_trade = result.total_pnl / result.total_trades

    # Profit factor
    gross_profit = sum(p for p in trade_pnls if p > 0)
    gross_loss = abs(sum(p for p in trade_pnls if p < 0))
    result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 9999.0

    # Sharpe ratio (annualized from trade returns)
    if len(trade_pnls) >= 2:
        mean_pnl = statistics.mean(trade_pnls)
        std_pnl = statistics.stdev(trade_pnls)
        if std_pnl > 0:
            # Approximate annualization: assume ~1 trade per bar
            bars_per_year = 252 * 24  # hourly bars
            trades_per_year = min(bars_per_year, result.total_trades * (bars_per_year / max(len(market_data), 1)))
            result.sharpe = round((mean_pnl / std_pnl) * (trades_per_year ** 0.5), 4)

    # Max drawdown
    equity_curve = []
    running = 0.0
    for pnl in trade_pnls:
        running += pnl
        equity_curve.append(running)

    peak = 0.0
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    result.max_drawdown = round(max_dd, 6)

    return result
