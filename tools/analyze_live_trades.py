#!/usr/bin/env python3
"""
Quick offline analyzer for live/paper trade logs.

Loads a trades CSV (produced by TradeLogger), filters, and reports simple stats.
"""

from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    timestamp_open: Optional[datetime]
    timestamp_close: Optional[datetime]
    symbol: str
    realized_pnl: float
    realized_pnl_pct: float


def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_trades(csv_path: Path) -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            trades.append(row)
    return trades


def _map_metric_key(metric: str) -> str:
    metric = metric.lower()
    if metric in ("pnl_pct", "realized_pnl_pct", "pnl_percent"):
        return "realized_pnl_pct"
    if metric in ("pnl", "realized_pnl", "pnl_usd"):
        return "realized_pnl"
    raise ValueError(f"Unsupported metric '{metric}'")


def _to_trade_record(row: Dict[str, Any]) -> TradeRecord:
    return TradeRecord(
        timestamp_open=_parse_iso_timestamp(row.get("timestamp_open")),
        timestamp_close=_parse_iso_timestamp(row.get("timestamp_close")),
        symbol=str(row.get("symbol", "")).upper(),
        realized_pnl=_to_float(row.get("realized_pnl")),
        realized_pnl_pct=_to_float(row.get("realized_pnl_pct")),
    )


def compute_max_drawdown(series: List[float]) -> float:
    peak = 0.0
    running = 0.0
    max_drawdown = 0.0

    for value in series:
        running += value
        peak = max(peak, running)
        max_drawdown = min(max_drawdown, running - peak)

    return max_drawdown


def analyze_trades(
    trades: List[Dict[str, Any]],
    *,
    symbol: Optional[str] = None,
    metric: str = "realized_pnl_pct",
    window_trades: int = 100,
) -> Dict[str, Any]:
    metric_key = _map_metric_key(metric)
    symbol_filter = symbol.upper() if symbol else None

    records: List[TradeRecord] = []
    for row in trades:
        record = _to_trade_record(row)
        if symbol_filter and record.symbol != symbol_filter:
            continue
        records.append(record)

    if window_trades and len(records) > window_trades:
        records = records[-window_trades:]

    if not records:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "avg_metric": 0.0,
            "median_metric": 0.0,
            "max_drawdown": 0.0,
            "avg_duration_minutes": 0.0,
        }

    metric_values = [
        record.realized_pnl_pct if metric_key == "realized_pnl_pct" else record.realized_pnl
        for record in records
    ]
    wins = sum(1 for value in metric_values if value > 0)
    durations = []
    for record in records:
        if record.timestamp_open and record.timestamp_close:
            delta = record.timestamp_close - record.timestamp_open
            durations.append(delta.total_seconds())

    max_dd = compute_max_drawdown(metric_values)

    return {
        "trades": len(records),
        "win_rate": wins / len(records) if records else 0.0,
        "avg_metric": mean(metric_values),
        "median_metric": median(metric_values),
        "max_drawdown": max_dd,
        "avg_duration_minutes": (mean(durations) / 60.0) if durations else 0.0,
        "symbol": symbol_filter or records[-1].symbol,
        "metric_key": metric_key,
    }


def format_summary(stats: Dict[str, Any], window_trades: int) -> str:
    metric_key = stats.get("metric_key", "realized_pnl_pct")
    metric_label = "pnl_pct" if metric_key == "realized_pnl_pct" else "realized_pnl"
    trade_count = stats.get("trades", 0)
    summary_lines = [
        f"Symbol: {stats.get('symbol', 'ALL')}",
        f"Window: last {window_trades} trades",
        f"Trades: {trade_count}",
        f"Win rate: {stats.get('win_rate', 0.0) * 100:.0f}%",
    ]

    if metric_key == "realized_pnl_pct":
        summary_lines.extend(
            [
                f"Avg {metric_label}: {stats.get('avg_metric', 0.0) * 100:.2f}%",
                f"Median {metric_label}: {stats.get('median_metric', 0.0) * 100:.2f}%",
                f"Max drawdown: {stats.get('max_drawdown', 0.0) * 100:.2f}%",
            ]
        )
    else:
        summary_lines.extend(
            [
                f"Avg {metric_label}: {stats.get('avg_metric', 0.0):.2f}",
                f"Median {metric_label}: {stats.get('median_metric', 0.0):.2f}",
                f"Max drawdown: {stats.get('max_drawdown', 0.0):.2f}",
            ]
        )

    summary_lines.append(
        f"Avg duration: {stats.get('avg_duration_minutes', 0.0):.1f} minutes"
    )
    return "\n".join(summary_lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze logged live/paper trades and emit simple stats."
    )
    parser.add_argument("--trades-csv", required=True, help="Path to trade log CSV")
    parser.add_argument("--symbol", help="Optional symbol filter (e.g., BTCUSDT)")
    parser.add_argument(
        "--window-trades",
        type=int,
        default=100,
        help="Analyze the last N trades (default: 100)",
    )
    parser.add_argument(
        "--metric",
        type=str,
        default="pnl_pct",
        choices=["pnl_pct", "realized_pnl", "pnl"],
        help="Metric to evaluate (default: pnl_pct)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: WARNING)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))

    csv_path = Path(args.trades_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"Trade CSV not found: {csv_path}")

    trades = load_trades(csv_path)
    stats = analyze_trades(
        trades,
        symbol=args.symbol,
        metric=args.metric,
        window_trades=args.window_trades,
    )
    summary = format_summary(stats, args.window_trades)
    print(summary)


if __name__ == "__main__":
    main()
