"""
Monte Carlo Simulation for backtest robustness validation.

Takes a set of trade returns from a completed backtest, randomly reshuffles
them N times, and reports confidence intervals for key metrics — detecting
whether observed performance relies on lucky trade ordering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResult:
    """Aggregate Monte Carlo simulation output."""

    num_simulations: int
    initial_equity: float
    # Confidence intervals (percentile values)
    final_equity_p5: float = 0.0
    final_equity_p25: float = 0.0
    final_equity_p50: float = 0.0
    final_equity_p75: float = 0.0
    final_equity_p95: float = 0.0
    max_dd_p5: float = 0.0
    max_dd_p50: float = 0.0
    max_dd_p95: float = 0.0
    sharpe_p5: float = 0.0
    sharpe_p50: float = 0.0
    sharpe_p95: float = 0.0
    # Pass/fail
    passed: bool = False
    failure_reasons: List[str] = field(default_factory=list)
    # Raw distributions (optional, for visualization)
    equity_distribution: List[float] = field(default_factory=list)
    drawdown_distribution: List[float] = field(default_factory=list)


class MonteCarloSimulator:
    """
    Runs Monte Carlo simulations by reshuffling trade returns.

    Parameters
    ----------
    num_simulations : int
        How many random reshuffles to run (default 1000).
    confidence_level : float
        Percentile threshold for pass/fail (default 0.05 = 5th percentile).
    min_final_equity_ratio : float
        Minimum ratio of final equity to initial at the confidence percentile
        (default 1.0 = must not lose money at the 5th percentile).
    max_drawdown_limit : float
        Maximum acceptable drawdown at the 95th percentile (default 0.30).
    seed : Optional[int]
        RNG seed for reproducibility.
    """

    def __init__(
        self,
        num_simulations: int = 1000,
        confidence_level: float = 0.05,
        min_final_equity_ratio: float = 1.0,
        max_drawdown_limit: float = 0.30,
        seed: Optional[int] = None,
    ):
        self.num_simulations = num_simulations
        self.confidence_level = confidence_level
        self.min_final_equity_ratio = min_final_equity_ratio
        self.max_drawdown_limit = max_drawdown_limit
        self.rng = np.random.default_rng(seed)

    def run(
        self,
        trade_returns: List[float],
        initial_equity: float = 10_000.0,
    ) -> MonteCarloResult:
        """
        Run Monte Carlo reshuffling on a list of per-trade P&L values.

        Parameters
        ----------
        trade_returns : list[float]
            Per-trade profit/loss amounts (absolute, not percentages).
        initial_equity : float
            Starting equity for each simulation.
        """
        if len(trade_returns) < 2:
            return MonteCarloResult(
                num_simulations=0,
                initial_equity=initial_equity,
                passed=False,
                failure_reasons=["Insufficient trades for Monte Carlo (need >= 2)"],
            )

        returns = np.array(trade_returns, dtype=np.float64)
        n_trades = len(returns)

        final_equities = np.empty(self.num_simulations)
        max_drawdowns = np.empty(self.num_simulations)
        sharpes = np.empty(self.num_simulations)

        for i in range(self.num_simulations):
            shuffled = self.rng.permutation(returns)
            equity_curve = initial_equity + np.cumsum(shuffled)
            equity_curve = np.insert(equity_curve, 0, initial_equity)

            final_equities[i] = equity_curve[-1]

            # Max drawdown
            peak = np.maximum.accumulate(equity_curve)
            dd = (peak - equity_curve) / np.where(peak > 0, peak, 1.0)
            max_drawdowns[i] = float(np.max(dd))

            # Sharpe (annualized, assuming ~252 trading days, 1 trade/day avg)
            if n_trades > 1 and np.std(shuffled) > 0:
                sharpes[i] = float(np.mean(shuffled) / np.std(shuffled) * np.sqrt(252))
            else:
                sharpes[i] = 0.0

        result = MonteCarloResult(
            num_simulations=self.num_simulations,
            initial_equity=initial_equity,
            final_equity_p5=float(np.percentile(final_equities, 5)),
            final_equity_p25=float(np.percentile(final_equities, 25)),
            final_equity_p50=float(np.percentile(final_equities, 50)),
            final_equity_p75=float(np.percentile(final_equities, 75)),
            final_equity_p95=float(np.percentile(final_equities, 95)),
            max_dd_p5=float(np.percentile(max_drawdowns, 5)),
            max_dd_p50=float(np.percentile(max_drawdowns, 50)),
            max_dd_p95=float(np.percentile(max_drawdowns, 95)),
            sharpe_p5=float(np.percentile(sharpes, 5)),
            sharpe_p50=float(np.percentile(sharpes, 50)),
            sharpe_p95=float(np.percentile(sharpes, 95)),
            equity_distribution=final_equities.tolist(),
            drawdown_distribution=max_drawdowns.tolist(),
        )

        # Pass/fail checks
        equity_threshold = initial_equity * self.min_final_equity_ratio
        if result.final_equity_p5 < equity_threshold:
            result.failure_reasons.append(
                f"5th percentile equity ${result.final_equity_p5:,.0f} "
                f"< ${equity_threshold:,.0f}"
            )
        if result.max_dd_p95 > self.max_drawdown_limit:
            result.failure_reasons.append(
                f"95th percentile max drawdown {result.max_dd_p95:.1%} "
                f"> limit {self.max_drawdown_limit:.1%}"
            )
        result.passed = len(result.failure_reasons) == 0

        logger.info(
            "Monte Carlo %s: Equity p5=$%.0f p50=$%.0f p95=$%.0f  MaxDD p95=%.1f%%",
            "PASSED" if result.passed else "FAILED",
            result.final_equity_p5,
            result.final_equity_p50,
            result.final_equity_p95,
            result.max_dd_p95 * 100,
        )
        return result

    @staticmethod
    def extract_trade_returns(backtest_result: Dict[str, Any]) -> List[float]:
        """
        Extract per-trade P&L values from a backtest result dict.

        Looks for ``trade_history`` or ``trades`` key containing dicts
        with a ``pnl`` or ``profit`` field.
        """
        trades = backtest_result.get("trade_history") or backtest_result.get("trades", [])
        returns: List[float] = []
        for t in trades:
            pnl = t.get("pnl") or t.get("profit") or t.get("realized_pnl", 0.0)
            returns.append(float(pnl))
        return returns
