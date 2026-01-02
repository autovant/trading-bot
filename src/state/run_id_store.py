from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def load_run_id(path: Path | str) -> Optional[str]:
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        raw = file_path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        if raw.startswith("{"):
            payload = json.loads(raw)
            return str(payload.get("run_id") or "").strip() or None
        return raw
    except Exception as exc:
        logger.warning("Failed to load run_id from %s: %s", file_path, exc)
        return None


def store_run_id(path: Path | str, run_id: str) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def resolve_run_id(
    *,
    env_var: str = "RUN_ID",
    path: Path | str = "data/run_id.json",
    prefix: str = "run",
) -> str:
    env_value = os.getenv(env_var)
    if env_value:
        return env_value.strip()

    stored = load_run_id(path)
    if stored:
        return stored

    generated = f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    store_run_id(path, generated)
    return generated
