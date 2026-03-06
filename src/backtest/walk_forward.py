"""
Walk-Forward Optimizer.

Splits historical data into sequential in-sample / out-of-sample windows,
runs a strategy on each pair, and aggregates performance to guard against
curve-fitting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WindowResult:
    """Performance for a single in-sample / out-of-sample window."""

    window_index: int
    in_sample_start: str
    in_sample_end: str
    out_sample_start: str
    out_sample_end: str
    in_sample_sharpe: float
    out_sample_sharpe: float
    in_sample_trades: int
    out_sample_trades: int
    out_sample_pnl: float
    out_sample_max_dd: float
    out_sample_win_rate: float
    degradation_pct: float  # (IS sharpe - OOS sharpe) / IS sharpe


@dataclass
class WalkForwardResult:
    """Aggregate walk-forward analysis result."""

    num_windows: int
    ratio: float
    windows: List[WindowResult] = field(default_factory=list)
    aggregate_oos_sharpe: float = 0.0
    aggregate_oos_pnl: float = 0.0
    aggregate_oos_max_dd: float = 0.0
    mean_degradation_pct: float = 0.0
    passed: bool = False
    failure_reasons: List[str] = field(default_factory=list)


class WalkForwardOptimizer:
    """
    Splits trade history into N sequential windows and evaluates out-of-sample
    performance to detect overfitting.

    Parameters
    ----------
    num_windows : int
        Number of walk-forward windows (default 5).
    ratio : float
        In-sample fraction of each window (default 0.70 = 70% IS, 30% OOS).
    min_oos_sharpe : float
        Minimum acceptable average OOS Sharpe (default 0.5).
    max_degradation_pct : float
        Max tolerable average degradation from IS→OOS (default 50%).
    """

    def __init__(
        self,
        num_windows: int = 5,
        ratio: float = 0.70,
        min_oos_sharpe: float = 0.5,
        max_degradation_pct: float = 50.0,
    ):
        if num_windows < 2:
            raise ValueError("num_windows must be >= 2")
        if not 0.1 <= ratio <= 0.95:
            raise ValueError("ratio must be between 0.10 and 0.95")
        self.num_windows = num_windows
        self.ratio = ratio
        self.min_oos_sharpe = min_oos_sharpe
        self.max_degradation_pct = max_degradation_pct

    async def run(
        self,
        backtest_fn: Callable[..., Any],
        symbol: str,
        start_date: str,
        end_date: str,
        **backtest_kwargs: Any,
    ) -> WalkForwardResult:
        """
        Execute walk-forward analysis.

        Parameters
        ----------
        backtest_fn : async callable
            Signature: ``async (symbol, start, end, **kw) -> dict`` returning
            at least ``sharpe_ratio``, ``total_trades``, ``total_pnl``,
            ``max_drawdown``, ``win_rate``.
        symbol : str
            Trading pair.
        start_date, end_date : str
            ISO-format date strings bounding the full evaluation period.
        """
        from datetime import datetime

        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
        total_seconds = (end_dt - start_dt).total_seconds()
        window_seconds = total_seconds / self.num_windows

        result = WalkForwardResult(
            num_windows=self.num_windows,
            ratio=self.ratio,
        )

        for i in range(self.num_windows):
            w_start = start_dt.timestamp() + i * window_seconds
            w_end = w_start + window_seconds
            split = w_start + window_seconds * self.ratio

            from datetime import timezone

            is_start = datetime.fromtimestamp(w_start, tz=timezone.utc).strftime("%Y-%m-%d")
            is_end = datetime.fromtimestamp(split, tz=timezone.utc).strftime("%Y-%m-%d")
            oos_start = is_end
            oos_end = datetime.fromtimestamp(w_end, tz=timezone.utc).strftime("%Y-%m-%d")

            logger.info("Window %d: IS %s→%s  OOS %s→%s", i, is_start, is_end, oos_start, oos_end)

            is_result = await backtest_fn(symbol=symbol, start=is_start, end=is_end, **backtest_kwargs)
            oos_result = await backtest_fn(symbol=symbol, start=oos_start, end=oos_end, **backtest_kwargs)

            is_sharpe = _extract(is_result, "sharpe_ratio", 0.0)
            oos_sharpe = _extract(oos_result, "sharpe_ratio", 0.0)
            degradation = (
                ((is_sharpe - oos_sharpe) / is_sharpe * 100) if is_sharpe > 0 else 0.0
            )

            window = WindowResult(
                window_index=i,
                in_sample_start=is_start,
                in_sample_end=is_end,
                out_sample_start=oos_start,
                out_sample_end=oos_end,
                in_sample_sharpe=is_sharpe,
                out_sample_sharpe=oos_sharpe,
                in_sample_trades=int(_extract(is_result, "total_trades", 0)),
                out_sample_trades=int(_extract(oos_result, "total_trades", 0)),
                out_sample_pnl=_extract(oos_result, "total_pnl", 0.0),
                out_sample_max_dd=_extract(oos_result, "max_drawdown", 0.0),
                out_sample_win_rate=_extract(oos_result, "win_rate", 0.0),
                degradation_pct=degradation,
            )
            result.windows.append(window)

        # Aggregate
        oos_sharpes = [w.out_sample_sharpe for w in result.windows]
        result.aggregate_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
        result.aggregate_oos_pnl = sum(w.out_sample_pnl for w in result.windows)
        result.aggregate_oos_max_dd = max(
            (w.out_sample_max_dd for w in result.windows), default=0.0
        )
        degradations = [w.degradation_pct for w in result.windows]
        result.mean_degradation_pct = float(np.mean(degradations)) if degradations else 0.0

        # Pass/fail
        if result.aggregate_oos_sharpe < self.min_oos_sharpe:
            result.failure_reasons.append(
                f"OOS Sharpe {result.aggregate_oos_sharpe:.2f} < min {self.min_oos_sharpe}"
            )
        if result.mean_degradation_pct > self.max_degradation_pct:
            result.failure_reasons.append(
                f"Mean degradation {result.mean_degradation_pct:.1f}% > max {self.max_degradation_pct}%"
            )
        result.passed = len(result.failure_reasons) == 0

        logger.info(
            "Walk-Forward %s: OOS Sharpe=%.2f  Degradation=%.1f%%",
            "PASSED" if result.passed else "FAILED",
            result.aggregate_oos_sharpe,
            result.mean_degradation_pct,
        )
        return result


def _extract(result: Dict[str, Any], key: str, default: float) -> float:
    """Extract a metric from a backtest result dict, handling nested 'stats' key."""
    if key in result:
        return float(result[key])
    stats = result.get("stats", {})
    if key in stats:
        return float(stats[key])
    # Try common aliases
    aliases = {
        "sharpe_ratio": ["sharpe"],
        "total_trades": ["num_trades"],
        "max_drawdown": ["max_drawdown_pct"],
    }
    for alias in aliases.get(key, []):
        if alias in result:
            return float(result[alias])
        if alias in stats:
            return float(stats[alias])
    return default
