"""
Portfolio-level risk manager for cross-agent constraint enforcement.

Maintains an aggregate view of all agent positions and enforces:
- Max total exposure across all agents
- Max correlation between agents (rolling 30-day returns)
- Max concentration per symbol
- API rate limit pooling per exchange

Called by the agent orchestrator before the ACT phase.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ..config import AgentRiskGuardrails

logger = logging.getLogger(__name__)


class RateLimitPool:
    """Token-bucket rate limiter shared across agents per exchange.

    Each agent gets ``per_agent_share`` tokens per second.
    Tokens refill at ``fill_rate`` per second up to ``capacity``.
    """

    def __init__(self, capacity: float = 10.0, fill_rate: float = 5.0):
        self.capacity = capacity
        self.fill_rate = fill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.fill_rate)
        self._last_refill = now

    def try_acquire(self, n: int = 1) -> bool:
        """Try to consume *n* tokens. Returns True if allowed."""
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return True
        return False

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens


class PortfolioRiskManager:
    """Aggregate risk view across all agents.

    Instantiated once by the agent orchestrator and queried before each
    agent's ACT phase to ensure portfolio-level constraints are met.
    """

    def __init__(
        self,
        max_total_exposure_usd: float = 50_000.0,
        max_symbol_concentration_pct: float = 0.40,
        max_agent_correlation: float = 0.70,
        max_total_agents: int = 10,
    ):
        self.max_total_exposure_usd = max_total_exposure_usd
        self.max_symbol_concentration_pct = max_symbol_concentration_pct
        self.max_agent_correlation = max_agent_correlation
        self.max_total_agents = max_total_agents

        # agent_id → {symbol → position_usd}
        self._positions: Dict[int, Dict[str, float]] = defaultdict(dict)
        # agent_id → [daily_return, ...]  (rolling 30 days)
        self._daily_returns: Dict[int, List[float]] = defaultdict(list)
        # exchange → RateLimitPool
        self._rate_pools: Dict[str, RateLimitPool] = {}

    # ------------------------------------------------------------------
    # Position tracking
    # ------------------------------------------------------------------
    def update_position(self, agent_id: int, symbol: str, notional_usd: float) -> None:
        """Update the tracked position for an agent/symbol pair."""
        if notional_usd == 0:
            self._positions[agent_id].pop(symbol, None)
        else:
            self._positions[agent_id][symbol] = notional_usd

    def remove_agent(self, agent_id: int) -> None:
        """Remove all tracked state for an agent."""
        self._positions.pop(agent_id, None)
        self._daily_returns.pop(agent_id, None)

    # ------------------------------------------------------------------
    # Daily return tracking (for correlation)
    # ------------------------------------------------------------------
    def record_daily_return(self, agent_id: int, daily_return: float) -> None:
        """Append a daily return for correlation computation.

        Only the most recent 30 values are kept.
        """
        returns = self._daily_returns[agent_id]
        returns.append(daily_return)
        if len(returns) > 30:
            self._daily_returns[agent_id] = returns[-30:]

    # ------------------------------------------------------------------
    # Pre-order checks
    # ------------------------------------------------------------------
    def check_order(
        self,
        agent_id: int,
        symbol: str,
        proposed_notional_usd: float,
        agent_guardrails: AgentRiskGuardrails,
    ) -> Tuple[bool, List[str]]:
        """Validate a proposed order against portfolio constraints.

        Returns (allowed, list_of_rejection_reasons).
        """
        rejections: List[str] = []

        # 1. Total exposure
        total = self._total_exposure()
        if total + proposed_notional_usd > self.max_total_exposure_usd:
            rejections.append(
                f"Total exposure ${total + proposed_notional_usd:,.0f} "
                f"would exceed limit ${self.max_total_exposure_usd:,.0f}"
            )

        # 2. Symbol concentration
        symbol_total = self._symbol_exposure(symbol)
        if total > 0:
            new_conc = (symbol_total + proposed_notional_usd) / (total + proposed_notional_usd)
            if new_conc > self.max_symbol_concentration_pct:
                rejections.append(
                    f"Symbol {symbol} concentration {new_conc:.1%} "
                    f"would exceed limit {self.max_symbol_concentration_pct:.1%}"
                )

        # 3. Per-agent position limit
        agent_pos_count = len(self._positions.get(agent_id, {}))
        if symbol not in self._positions.get(agent_id, {}) and agent_pos_count >= agent_guardrails.max_open_positions:
            rejections.append(
                f"Agent {agent_id} has {agent_pos_count} positions, "
                f"max is {agent_guardrails.max_open_positions}"
            )

        # 4. Per-agent max position size
        if proposed_notional_usd > agent_guardrails.max_position_size_usd:
            rejections.append(
                f"Position ${proposed_notional_usd:,.0f} exceeds "
                f"agent limit ${agent_guardrails.max_position_size_usd:,.0f}"
            )

        return (len(rejections) == 0, rejections)

    # ------------------------------------------------------------------
    # Correlation check
    # ------------------------------------------------------------------
    def check_correlation(self, agent_id: int) -> Tuple[bool, Optional[str]]:
        """Check if the agent's returns correlate too highly with any other agent."""
        my_returns = self._daily_returns.get(agent_id, [])
        if len(my_returns) < 5:
            return (True, None)  # Not enough data

        for other_id, other_returns in self._daily_returns.items():
            if other_id == agent_id or len(other_returns) < 5:
                continue
            corr = self._pearson(my_returns, other_returns)
            if abs(corr) > self.max_agent_correlation:
                return (
                    False,
                    f"Correlation with agent {other_id}: {corr:.2f} "
                    f"exceeds limit {self.max_agent_correlation}",
                )

        return (True, None)

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def get_rate_pool(self, exchange: str) -> RateLimitPool:
        """Get or create a rate limit pool for the given exchange."""
        if exchange not in self._rate_pools:
            self._rate_pools[exchange] = RateLimitPool()
        return self._rate_pools[exchange]

    def try_acquire_rate(self, exchange: str, n: int = 1) -> bool:
        """Try to consume API rate tokens for the given exchange."""
        return self.get_rate_pool(exchange).try_acquire(n)

    # ------------------------------------------------------------------
    # Aggregate queries
    # ------------------------------------------------------------------
    def _total_exposure(self) -> float:
        return sum(
            abs(v) for positions in self._positions.values() for v in positions.values()
        )

    def _symbol_exposure(self, symbol: str) -> float:
        return sum(
            abs(positions.get(symbol, 0))
            for positions in self._positions.values()
        )

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Return a summary of the current portfolio risk state."""
        total = self._total_exposure()
        symbol_exposures: Dict[str, float] = defaultdict(float)
        for positions in self._positions.values():
            for sym, val in positions.items():
                symbol_exposures[sym] += abs(val)

        return {
            "total_exposure_usd": total,
            "max_exposure_usd": self.max_total_exposure_usd,
            "utilization_pct": total / self.max_total_exposure_usd if self.max_total_exposure_usd > 0 else 0,
            "active_agents": len(self._positions),
            "symbol_exposures": dict(symbol_exposures),
        }

    # ------------------------------------------------------------------
    # Math helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> float:
        """Compute Pearson correlation between two series of equal length."""
        n = min(len(x), len(y))
        if n < 2:
            return 0.0
        x, y = x[-n:], y[-n:]
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y, strict=True))
        std_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
        std_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
        if std_x == 0 or std_y == 0:
            return 0.0
        return cov / (std_x * std_y)
