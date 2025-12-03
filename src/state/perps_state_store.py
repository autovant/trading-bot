from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class PerpsState:
    peak_equity: float
    daily_pnl_by_date: Dict[str, float]
    consecutive_losses: int
    version: int = 1


def load_perps_state(path: Path | str) -> Optional[PerpsState]:
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        version = data.get("version")
        if version != 1:
            logger.warning(
                "Unknown perps state version %s at %s; ignoring persisted state.",
                version,
                file_path,
            )
            return None
        return PerpsState(
            peak_equity=float(data.get("peak_equity", 0.0)),
            daily_pnl_by_date={
                str(k): float(v) for k, v in data.get("daily_pnl_by_date", {}).items()
            },
            consecutive_losses=int(data.get("consecutive_losses", 0)),
            version=version,
        )
    except Exception as exc:
        logger.warning("Failed to load perps state from %s: %s", file_path, exc)
        return None


def save_perps_state(path: Path | str, state: PerpsState) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": state.version,
        "peak_equity": state.peak_equity,
        "daily_pnl_by_date": state.daily_pnl_by_date,
        "consecutive_losses": state.consecutive_losses,
    }
    file_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
