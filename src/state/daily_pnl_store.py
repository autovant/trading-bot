from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class DailyPnlStore:
    """JSON-backed store tracking per-account daily realized PnL."""

    path: str
    _data: Dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path = str(self.path)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        store_path = Path(self.path)
        if not store_path.exists():
            return {"accounts": {}}
        try:
            payload = json.loads(store_path.read_text())
            if not isinstance(payload, dict):
                return {"accounts": {}}
            if "accounts" not in payload or not isinstance(payload["accounts"], dict):
                payload["accounts"] = {}
            return payload
        except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
            return {"accounts": {}}

    def save(self) -> None:
        store_path = Path(self.path)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = store_path.with_suffix(store_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp_path, store_path)

    def update_pnl(self, account_id: str, date_key: str, delta_pnl: float) -> float:
        accounts = self._data.setdefault("accounts", {})
        account_entry = accounts.setdefault(account_id, {})
        day_entry = account_entry.setdefault(date_key, {"realized_pnl_usd": 0.0})
        day_entry["realized_pnl_usd"] = float(
            day_entry.get("realized_pnl_usd", 0.0)
        ) + float(delta_pnl)
        self.save()
        return day_entry["realized_pnl_usd"]

    def get_pnl(self, account_id: str, date_key: str) -> float:
        accounts = self._data.get("accounts", {})
        account_entry = accounts.get(account_id, {})
        day_entry = account_entry.get(date_key, {})
        try:
            return float(day_entry.get("realized_pnl_usd", 0.0))
        except (TypeError, ValueError):
            return 0.0
