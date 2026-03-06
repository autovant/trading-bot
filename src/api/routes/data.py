"""
API routes for historical data management.

Provides endpoints to trigger data downloads and inspect available datasets.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

data_router = APIRouter(tags=["data"])

DATA_DIR = Path("data/bars")

# Only allow safe filenames: alphanumeric, underscore, dash, dot
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9_\-]+\.parquet$")

# In-memory job status tracker
_download_jobs: Dict[str, dict] = {}


class DataDownloadRequest(BaseModel):
    symbol: str = Field(..., description="Trading pair (e.g. BTCUSDT)")
    timeframe: str = Field(..., description="Candle interval (1m, 5m, 15m, 1h, 4h, 1d)")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date: str = Field(..., description="End date YYYY-MM-DD")
    source: str = Field(default="binance", description="Data source")

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        allowed = {"1m", "5m", "15m", "1h", "4h", "1d"}
        if v not in allowed:
            raise ValueError(f"timeframe must be one of {allowed}")
        return v

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9]{2,20}$", v.upper()):
            raise ValueError("symbol must be 2-20 alphanumeric characters")
        return v.upper()

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("date must be in YYYY-MM-DD format")
        return v


class DataDownloadResponse(BaseModel):
    job_id: str
    status: str
    message: str


class DatasetInfo(BaseModel):
    filename: str
    symbol: str
    timeframe: str
    row_count: int
    start_timestamp: Optional[int] = None
    end_timestamp: Optional[int] = None
    file_size_bytes: int


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
    output_path: Optional[str] = None
    error: Optional[str] = None


async def _run_download(job_id: str, request: DataDownloadRequest) -> None:
    """Background task that runs the data download."""
    from tools.data_downloader import DataDownloader

    _download_jobs[job_id]["status"] = "running"
    try:
        downloader = DataDownloader(output_dir=str(DATA_DIR))
        path = await downloader.download(
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            source=request.source,
        )
        _download_jobs[job_id].update(
            {"status": "completed", "output_path": path, "message": "Download complete"}
        )
    except Exception:
        logger.exception("Download failed for job %s", job_id)
        _download_jobs[job_id].update(
            {"status": "failed", "error": "Download failed due to an internal error", "message": "Download failed"}
        )


@data_router.post("/api/data/download", response_model=DataDownloadResponse, status_code=202)
async def trigger_download(
    request: DataDownloadRequest,
    background_tasks: BackgroundTasks,
) -> DataDownloadResponse:
    """Trigger a data download job. Returns job_id for status polling."""
    job_id = str(uuid.uuid4())
    _download_jobs[job_id] = {
        "status": "queued",
        "message": f"Queued download for {request.symbol} {request.timeframe}",
        "output_path": None,
        "error": None,
    }
    background_tasks.add_task(_run_download, job_id, request)
    return DataDownloadResponse(
        job_id=job_id,
        status="queued",
        message=f"Download queued for {request.symbol} {request.timeframe}",
    )


@data_router.get("/api/data/download/{job_id}", response_model=JobStatusResponse)
async def get_download_status(job_id: str) -> JobStatusResponse:
    """Check the status of a download job."""
    job = _download_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(job_id=job_id, **job)


@data_router.get("/api/data/datasets", response_model=List[DatasetInfo])
async def list_datasets() -> List[DatasetInfo]:
    """List available Parquet datasets in data/bars/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    datasets: List[DatasetInfo] = []

    for path in sorted(DATA_DIR.glob("*.parquet")):
        if not _SAFE_FILENAME.match(path.name):
            continue
        try:
            info = _read_dataset_info(path)
            datasets.append(info)
        except Exception:
            continue

    return datasets


@data_router.get("/api/data/datasets/{filename}", response_model=DatasetInfo)
async def get_dataset_info(filename: str) -> DatasetInfo:
    """Get metadata about a specific dataset (row count, date range, etc)."""
    if not _SAFE_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = DATA_DIR / filename
    # Resolve and verify the path stays within DATA_DIR
    resolved = path.resolve()
    if not str(resolved).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Dataset not found")

    return _read_dataset_info(resolved)


@data_router.delete("/api/data/datasets/{filename}")
async def delete_dataset(filename: str) -> Response:
    """Delete a Parquet dataset file."""
    if not _SAFE_FILENAME.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    path = DATA_DIR / filename
    resolved = path.resolve()
    if not str(resolved).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Dataset not found")

    resolved.unlink()
    return Response(status_code=204)


def _read_dataset_info(path: Path) -> DatasetInfo:
    """Read metadata from a Parquet file without loading all data."""
    df = pd.read_parquet(path, columns=["timestamp"])
    row_count = len(df)

    start_ts = int(df["timestamp"].min()) if row_count > 0 else None
    end_ts = int(df["timestamp"].max()) if row_count > 0 else None

    # Parse symbol and timeframe from filename (e.g. BTCUSDT_5m.parquet)
    stem = path.stem
    parts = stem.rsplit("_", 1)
    symbol = parts[0] if len(parts) == 2 else stem
    timeframe = parts[1] if len(parts) == 2 else "unknown"

    return DatasetInfo(
        filename=path.name,
        symbol=symbol,
        timeframe=timeframe,
        row_count=row_count,
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        file_size_bytes=path.stat().st_size,
    )
