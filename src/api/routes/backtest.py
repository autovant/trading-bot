from datetime import datetime, timezone
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException, BackgroundTasks, status
from src.api.models import BacktestRequest, BacktestJobResponse
# In a real refactor, we would move _BacktestJob logic to a dedicated service
# For now, we will assume a service or global helper access.
# Since backtesting is stateful (job queue), we need to share that state.
# Ideally: src/services/backtester.py
# For now, implementing as a placeholder to be wired in main.py or via robust service injection.

backtest_router = APIRouter()

# Globals/Service placeholder
_backtest_jobs: Dict[str, Any] = {} # This will need to be imported or injected

@backtest_router.post("/api/backtest/run", response_model=BacktestJobResponse)
async def submit_backtest(
    request: BacktestRequest, 
    background_tasks: BackgroundTasks
) -> BacktestJobResponse:
    # Logic to submit job
    # We need to implement the actual running logic or import it
    raise HTTPException(status_code=501, detail="Refactor in progress - Service not wired")

@backtest_router.get("/api/backtest/status/{job_id}", response_model=BacktestJobResponse)
async def get_backtest_status(job_id: str) -> BacktestJobResponse:
    if job_id not in _backtest_jobs:
         raise HTTPException(status_code=404, detail="Job not found")
    # return mapped job
    return _backtest_jobs[job_id]
