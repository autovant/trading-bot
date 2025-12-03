from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(timestamp: Optional[str]) -> Optional[datetime]:
    if not timestamp:
        return None
    try:
        if timestamp.endswith("Z"):
            timestamp = timestamp.replace("Z", "+00:00")
        return datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None


class SymbolHealthStore:
    """JSON-backed store tracking runtime symbol health status."""

    def __init__(self, path: str):
        self.path = str(path)
        self._data = self._load()

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "last_status": None,
            "last_evaluated_at": None,
            "blocked_until": None,
            "last_reasons": [],
        }

    def _load(self) -> Dict[str, Any]:
        store_path = Path(self.path)
        if not store_path.exists():
            return {"symbols": {}}
        try:
            payload = json.loads(store_path.read_text())
            if not isinstance(payload, dict):
                return {"symbols": {}}
            if "symbols" not in payload or not isinstance(payload["symbols"], dict):
                payload["symbols"] = {}
            return payload
        except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
            return {"symbols": {}}

    def _save(self) -> None:
        store_path = Path(self.path)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = store_path.with_suffix(store_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp_path, store_path)

    def get_symbol_state(self, symbol: str) -> Dict[str, Any]:
        symbols = self._data.setdefault("symbols", {})
        state = symbols.get(symbol.upper(), {})
        merged = self._default_state()
        merged.update(state if isinstance(state, dict) else {})
        return merged

    def update_symbol_state(
        self,
        symbol: str,
        status: str,
        reasons: List[str],
        blocked_until: Optional[str],
        evaluated_at: Optional[str] = None,
    ) -> None:
        symbol_key = symbol.upper()
        payload = self._data.setdefault("symbols", {})
        entry = self._default_state()
        entry.update(payload.get(symbol_key, {}))

        entry["last_status"] = status
        entry["last_reasons"] = reasons or []
        entry["blocked_until"] = blocked_until
        entry["last_evaluated_at"] = evaluated_at or _format_iso(
            datetime.now(timezone.utc)
        )

        payload[symbol_key] = entry
        self._save()

    def is_blocked(self, symbol: str, now: Optional[datetime] = None) -> bool:
        state = self.get_symbol_state(symbol)
        blocked_until = _parse_iso(state.get("blocked_until"))
        now_ts = now or datetime.now(timezone.utc)
        return bool(blocked_until and blocked_until > now_ts)

    def get_effective_size_multiplier(
        self, symbol: str, warning_size_multiplier: float = 1.0
    ) -> float:
        state = self.get_symbol_state(symbol)
        status = str(state.get("last_status") or "").upper()
        if status == "WARNING":
            return warning_size_multiplier
        if status == "FAILING":
            return 0.0
        return 1.0
