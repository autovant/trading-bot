from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TradeLogger:
    """
    Lightweight CSV logger for completed trades.

    Appends rows to a CSV file and writes the header if the file is missing or empty.
    """

    HEADERS = [
        "timestamp_open",
        "timestamp_close",
        "symbol",
        "side",
        "size",
        "notional",
        "entry_price",
        "exit_price",
        "realized_pnl",
        "realized_pnl_pct",
        "fees",
        "config_id",
        "strategy_name",
        "account_equity_before",
        "account_equity_after",
        "risk_blocked_before_entry",
        "extra",
    ]

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

    def _ensure_header(self) -> None:
        if self.csv_path.exists() and self.csv_path.stat().st_size > 0:
            return

        with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.HEADERS)
            writer.writeheader()

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _format_bool(value: Any) -> str:
        if isinstance(value, bool):
            return "YES" if value else "NO"
        if value in (None, ""):
            return ""
        return str(value)

    @staticmethod
    def _format_float(value: Any, default: Any = "") -> Any:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _format_extra(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value)
        except (TypeError, ValueError):
            return str(value)

    def log_completed_trade(self, trade_info: Dict[str, Any]) -> None:
        """
        Append a completed trade to the CSV file.

        trade_info should include the core schema fields; missing optional fields
        are filled with defaults.
        """

        self._ensure_header()

        row = {key: "" for key in self.HEADERS}
        row.update(
            {
                "timestamp_open": self._format_timestamp(
                    trade_info.get("timestamp_open")
                ),
                "timestamp_close": self._format_timestamp(
                    trade_info.get("timestamp_close")
                ),
                "symbol": trade_info.get("symbol", ""),
                "side": trade_info.get("side", ""),
                "size": self._format_float(trade_info.get("size"), default=""),
                "notional": self._format_float(trade_info.get("notional"), default=""),
                "entry_price": self._format_float(
                    trade_info.get("entry_price"), default=""
                ),
                "exit_price": self._format_float(
                    trade_info.get("exit_price"), default=""
                ),
                "realized_pnl": self._format_float(
                    trade_info.get("realized_pnl"), default=""
                ),
                "realized_pnl_pct": self._format_float(
                    trade_info.get("realized_pnl_pct"), default=""
                ),
                "fees": self._format_float(trade_info.get("fees"), default=0.0),
                "config_id": trade_info.get("config_id", ""),
                "strategy_name": trade_info.get("strategy_name", ""),
                "account_equity_before": self._format_float(
                    trade_info.get("account_equity_before"), default=""
                ),
                "account_equity_after": self._format_float(
                    trade_info.get("account_equity_after"), default=""
                ),
                "risk_blocked_before_entry": self._format_bool(
                    trade_info.get("risk_blocked_before_entry")
                ),
                "extra": self._format_extra(trade_info.get("extra")),
            }
        )

        with self.csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.HEADERS)
            writer.writerow(row)

        logger.info(
            "TradeLogger: logged trade %s %s size=%s pnl=%s",
            row["symbol"],
            row["side"],
            row["size"],
            row["realized_pnl"],
        )
