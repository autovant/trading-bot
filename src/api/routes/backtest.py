import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.models import BacktestRequest
from src.database import DatabaseManager

logger = logging.getLogger(__name__)

backtest_router = APIRouter(tags=["backtest"])


# Dependencies — overridden at app startup
async def get_db() -> DatabaseManager:
    raise NotImplementedError


class BacktestResultsSummary(BaseModel):
    job_id: str
    symbol: str
    status: str
    start_date: str
    end_date: str
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@backtest_router.post("/api/backtests", status_code=202)
async def submit_backtest(
    request: BacktestRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseManager = Depends(get_db),
):
    """Submit a backtest job. Persisted to DB and runs as background task."""
    job_id = str(uuid.uuid4())
    await db.create_backtest_job(
        job_id=job_id,
        symbol=request.symbol,
        start_date=request.start,
        end_date=request.end,
    )
    background_tasks.add_task(_run_backtest, job_id, request, db)
    return {"job_id": job_id, "status": "queued"}


@backtest_router.get("/api/backtests/history")
async def list_backtests(
    limit: int = 50,
    db: DatabaseManager = Depends(get_db),
):
    """List past backtest runs with summary stats."""
    jobs = await db.list_backtest_jobs(limit=limit)
    return {"jobs": jobs, "total": len(jobs)}


@backtest_router.get("/api/backtests/{job_id}")
async def get_backtest_status(
    job_id: str,
    db: DatabaseManager = Depends(get_db),
):
    """Get status of a backtest job."""
    job = await db.get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@backtest_router.get("/api/backtests/{job_id}/results")
async def get_backtest_results(
    job_id: str,
    db: DatabaseManager = Depends(get_db),
):
    """Get full results of a completed backtest job."""
    job = await db.get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail=f"Job is {job.get('status')}, not yet completed")
    return {
        "job_id": job_id,
        "symbol": job.get("symbol"),
        "start_date": job.get("start_date"),
        "end_date": job.get("end_date"),
        "result": job.get("result_json"),
    }


async def _run_backtest(job_id: str, request: BacktestRequest, db: DatabaseManager):
    """Run the actual backtest in the background, with optional WF/MC analysis."""
    try:
        await db.update_backtest_job(job_id, status="running")
        try:
            from tools.backtest import run_backtest as engine_run
            result = await engine_run(
                symbol=request.symbol,
                start=request.start,
                end=request.end,
                strategy_name=request.strategy_name,
                strategy_params=request.strategy_params,
            )

            # Epic 3.1 — Walk-Forward analysis
            if request.walk_forward_windows and request.walk_forward_windows >= 2:
                try:
                    import dataclasses

                    from src.backtest.walk_forward import WalkForwardOptimizer
                    wf = WalkForwardOptimizer(num_windows=request.walk_forward_windows)
                    wf_result = await wf.run(
                        backtest_fn=engine_run,
                        symbol=request.symbol,
                        start_date=request.start,
                        end_date=request.end,
                    )
                    result["walk_forward"] = dataclasses.asdict(wf_result)
                except Exception:
                    logger.exception("Walk-forward analysis failed")
                    result["walk_forward_error"] = "Walk-forward analysis encountered an error"

            # Epic 3.2 — Monte Carlo simulation
            if request.monte_carlo_runs and request.monte_carlo_runs > 0:
                try:
                    import dataclasses

                    from src.backtest.monte_carlo import MonteCarloSimulator
                    mc = MonteCarloSimulator(num_simulations=request.monte_carlo_runs)
                    trade_returns = MonteCarloSimulator.extract_trade_returns(result)
                    mc_result = mc.run(
                        trade_returns=trade_returns,
                        initial_equity=result.get("initial_balance", 10_000),
                    )
                    # Don't store full distributions in DB (too large)
                    mc_dict = dataclasses.asdict(mc_result)
                    mc_dict.pop("equity_distribution", None)
                    mc_dict.pop("drawdown_distribution", None)
                    result["monte_carlo"] = mc_dict
                except Exception:
                    logger.exception("Monte-Carlo simulation failed")
                    result["monte_carlo_error"] = "Monte-Carlo simulation encountered an error"

            await db.update_backtest_job(
                job_id, status="completed", result_json=result,
            )
        except ImportError:
            await db.update_backtest_job(
                job_id, status="failed",
                error="Backtest engine not available (tools.backtest module not found)",
            )
    except Exception:
        logger.exception("Backtest job %s failed", job_id)
        await db.update_backtest_job(
            job_id, status="failed", error="Backtest execution encountered an error",
        )


# ---------------------------------------------------------------------------
# Epic 3.3 — Strategy Comparison
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    """Request body for comparing multiple backtest runs."""
    job_ids: List[str] = Field(..., min_length=2, max_length=10)


@backtest_router.post("/api/backtests/compare")
async def compare_backtests(
    request: CompareRequest,
    db: DatabaseManager = Depends(get_db),
):
    """
    Compare multiple completed backtests side-by-side.

    Returns per-job stats plus a paired t-test of daily returns between the
    first job and each subsequent job for statistical significance.
    """
    from scipy import stats as sp_stats

    jobs: List[Dict[str, Any]] = []
    for jid in request.job_ids:
        job = await db.get_backtest_job(jid)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {jid} not found")
        if job.get("status") != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Job {jid} not completed (status={job.get('status')})",
            )
        jobs.append(job)

    # Build comparison table
    comparison: List[Dict[str, Any]] = []
    daily_returns_map: Dict[str, List[float]] = {}

    for job in jobs:
        result = job.get("result_json") or {}
        stats = result.get("stats", result)
        jid = job.get("job_id", job.get("id", ""))

        # Extract equity curve for daily returns
        equity_curve = result.get("equity_curve", [])
        daily_returns: List[float] = []
        if len(equity_curve) >= 2:
            for k in range(1, len(equity_curve)):
                prev_eq = equity_curve[k - 1]
                curr_eq = equity_curve[k]
                prev_val = prev_eq.get("equity", prev_eq) if isinstance(prev_eq, dict) else prev_eq
                curr_val = curr_eq.get("equity", curr_eq) if isinstance(curr_eq, dict) else curr_eq
                if prev_val and prev_val != 0:
                    daily_returns.append((curr_val - prev_val) / prev_val)
        daily_returns_map[jid] = daily_returns

        comparison.append({
            "job_id": jid,
            "symbol": job.get("symbol"),
            "start_date": job.get("start_date"),
            "end_date": job.get("end_date"),
            "sharpe_ratio": _safe_float(stats, "sharpe_ratio"),
            "total_pnl": _safe_float(stats, "total_pnl"),
            "max_drawdown": _safe_float(stats, "max_drawdown"),
            "win_rate": _safe_float(stats, "win_rate"),
            "total_trades": _safe_int(stats, "total_trades"),
            "profit_factor": _safe_float(stats, "profit_factor"),
        })

    # Statistical significance (paired t-test vs. first job)
    significance: List[Dict[str, Any]] = []
    baseline_id = request.job_ids[0]
    baseline_returns = daily_returns_map.get(baseline_id, [])

    for jid in request.job_ids[1:]:
        other_returns = daily_returns_map.get(jid, [])
        entry: Dict[str, Any] = {
            "baseline_job_id": baseline_id,
            "compare_job_id": jid,
        }
        min_len = min(len(baseline_returns), len(other_returns))
        if min_len >= 5:
            t_stat, p_value = sp_stats.ttest_rel(
                baseline_returns[:min_len], other_returns[:min_len]
            )
            entry["t_statistic"] = float(t_stat)
            entry["p_value"] = float(p_value)
            entry["significant_at_5pct"] = p_value < 0.05
        else:
            entry["t_statistic"] = None
            entry["p_value"] = None
            entry["significant_at_5pct"] = None
            entry["note"] = "Insufficient data points for paired t-test"
        significance.append(entry)

    return {
        "comparison": comparison,
        "significance_tests": significance,
    }


def _safe_float(d: Dict[str, Any], key: str) -> Optional[float]:
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(d: Dict[str, Any], key: str) -> Optional[int]:
    v = d.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

