#!/usr/bin/env python3
"""
Health check to compare live trading performance against sweep best-config expectations.

Loads best_configs.json and a live trades CSV, computes recent live metrics per symbol,
and evaluates whether performance is in line with sweep benchmarks.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Thresholds can be tuned as needed
WIN_RATE_DROP_WARN = 0.15
WIN_RATE_DROP_FAIL = 0.25
PNL_PCT_GAP_WARN = 0.20
PNL_PCT_GAP_FAIL = 0.35
DD_MULT_WARN = 1.2
DD_MULT_FAIL = 1.5

STATUS_ORDER = {"OK": 0, "WARNING": 1, "FAILING": 2}


@dataclass
class Thresholds:
    win_rate_drop_warn: float = WIN_RATE_DROP_WARN
    win_rate_drop_fail: float = WIN_RATE_DROP_FAIL
    pnl_pct_gap_warn: float = PNL_PCT_GAP_WARN
    pnl_pct_gap_fail: float = PNL_PCT_GAP_FAIL
    drawdown_mult_warn: float = DD_MULT_WARN
    drawdown_mult_fail: float = DD_MULT_FAIL


@dataclass
class ParsedTrade:
    symbol: str
    config_id: str
    realized_pnl: float
    realized_pnl_pct: float
    timestamp_open: Optional[datetime]
    timestamp_close: Optional[datetime]
    row_index: int


def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _map_metric_key(metric: str) -> str:
    metric = metric.lower()
    if metric in ("pnl_pct", "realized_pnl_pct", "pnl_percent"):
        return "realized_pnl_pct"
    if metric in ("pnl", "realized_pnl", "pnl_usd"):
        return "realized_pnl"
    if metric in ("sharpe", "win_rate"):
        # We compute these from pnl_pct-based trades; keep the primary metric on pnl_pct.
        return "realized_pnl_pct"
    raise ValueError(f"Unsupported metric '{metric}'")


def compute_max_drawdown(values: List[float]) -> float:
    peak = 0.0
    running = 0.0
    max_drawdown = 0.0

    for value in values:
        running += value
        peak = max(peak, running)
        max_drawdown = min(max_drawdown, running - peak)

    return max_drawdown


def load_best_configs(path: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Best-configs JSON not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError("Best-configs JSON must contain an object at the top level.")

    schema_version = str(payload.get("schema_version", ""))
    if not schema_version.startswith("1."):
        raise ValueError(
            f"Unsupported best-configs schema_version '{schema_version}'. Expected '1.x'."
        )

    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("Best-configs JSON must include a non-empty 'symbols' list.")

    mapping: Dict[str, Dict[str, Any]] = {}
    for entry in symbols:
        if not isinstance(entry, dict):
            raise ValueError("Each entry in 'symbols' must be an object.")
        symbol = entry.get("symbol")
        if not symbol:
            raise ValueError("Best-config entry missing required 'symbol' field.")
        mapping[str(symbol).upper()] = entry

    meta = {
        "metric": payload.get("metric"),
        "generated_at": payload.get("generated_at"),
        "path": str(path),
    }
    return mapping, meta


def load_trades(csv_path: Path) -> List[Dict[str, Any]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Trade CSV not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Trade CSV is missing a header row.")
        expected_columns = {
            "symbol",
            "config_id",
            "realized_pnl_pct",
            "realized_pnl",
            "timestamp_close",
            "timestamp_open",
        }
        missing = expected_columns - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"Trade CSV missing required columns: {', '.join(sorted(missing))}"
            )

        trades: List[Dict[str, Any]] = []
        for row in reader:
            trades.append(row)
    return trades


def parse_trades(rows: List[Dict[str, Any]]) -> List[ParsedTrade]:
    parsed: List[ParsedTrade] = []
    for idx, row in enumerate(rows):
        parsed.append(
            ParsedTrade(
                symbol=str(row.get("symbol", "")).upper(),
                config_id=str(row.get("config_id", "") or ""),
                realized_pnl=_to_float(row.get("realized_pnl")) or 0.0,
                realized_pnl_pct=_to_float(row.get("realized_pnl_pct")) or 0.0,
                timestamp_open=_parse_iso_timestamp(row.get("timestamp_open")),
                timestamp_close=_parse_iso_timestamp(row.get("timestamp_close")),
                row_index=idx,
            )
        )
    return parsed


def _metric_value(trade: ParsedTrade, metric_key: str) -> float:
    if metric_key == "realized_pnl":
        return trade.realized_pnl
    return trade.realized_pnl_pct


def compute_live_metrics(
    trades: List[ParsedTrade],
    *,
    metric_key: str,
) -> Dict[str, Any]:
    if not trades:
        return {
            "num_trades": 0,
            "win_rate": 0.0,
            "avg_value": 0.0,
            "median_value": 0.0,
            "max_drawdown": 0.0,
            "metric_key": metric_key,
        }

    metric_values = [_metric_value(trade, metric_key) for trade in trades]
    wins = sum(1 for value in metric_values if value > 0)
    max_dd = compute_max_drawdown(metric_values)

    return {
        "num_trades": len(trades),
        "win_rate": wins / len(trades),
        "avg_value": mean(metric_values),
        "median_value": median(metric_values),
        "max_drawdown": max_dd,
        "metric_key": metric_key,
    }


def extract_sweep_metrics(
    entry: Dict[str, Any],
    *,
    metric_key: str,
) -> Dict[str, Optional[float]]:
    metrics = entry.get("metrics") or {}

    def first_number(keys: Iterable[str]) -> Optional[float]:
        for key in keys:
            if key in metrics:
                value = _to_float(metrics.get(key))
                if value is not None:
                    return value
            if key in entry:
                value = _to_float(entry.get(key))
                if value is not None:
                    return value
        return None

    avg_value = first_number(
        [
            "pnl_pct",
            "avg_pnl_pct",
            "metric_mean",
            "pnl",
            "avg_pnl",
        ]
    )
    win_rate = first_number(["win_rate"])
    max_drawdown = first_number(["max_drawdown", "max_drawdown_pct"])
    num_trades = first_number(["num_trades", "trades", "total_trades"])

    if metric_key == "realized_pnl":
        # Prefer pnl-based metrics when the caller asks for pnl
        avg_value = first_number(
            ["pnl", "avg_pnl", "metric_mean", "pnl_pct", "avg_pnl_pct"]
        )

    return {
        "avg_value": avg_value,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "num_trades": num_trades,
    }


def evaluate_symbol_health(
    sweep_metrics: Dict[str, Optional[float]],
    live_metrics: Dict[str, float],
    thresholds: Thresholds,
) -> Tuple[str, List[str]]:
    status = "OK"
    reasons: List[str] = []

    def flag(level: str, reason: str) -> None:
        nonlocal status
        if STATUS_ORDER[level] > STATUS_ORDER[status]:
            status = level
        if reason not in reasons:
            reasons.append(reason)

    sweep_win = sweep_metrics.get("win_rate")
    live_win = live_metrics.get("win_rate")
    if sweep_win is not None and live_win is not None:
        drop = sweep_win - live_win
        if drop >= thresholds.win_rate_drop_fail:
            flag("FAILING", "win_rate_drop")
        elif drop >= thresholds.win_rate_drop_warn:
            flag("WARNING", "win_rate_drop")

    sweep_avg = sweep_metrics.get("avg_value")
    live_avg = live_metrics.get("avg_value")
    if sweep_avg is not None and live_avg is not None:
        gap = sweep_avg - live_avg
        if gap >= thresholds.pnl_pct_gap_fail:
            flag("FAILING", "avg_pnl_gap")
        elif gap >= thresholds.pnl_pct_gap_warn:
            flag("WARNING", "avg_pnl_gap")
        if live_avg < 0:
            flag("FAILING", "negative_avg_pnl")

    sweep_dd = sweep_metrics.get("max_drawdown")
    live_dd = live_metrics.get("max_drawdown")
    if sweep_dd is not None and live_dd is not None and sweep_dd != 0:
        dd_mult = abs(live_dd) / max(abs(sweep_dd), 1e-9)
        if dd_mult >= thresholds.drawdown_mult_fail:
            flag("FAILING", "drawdown_exceeds_limit")
        elif dd_mult >= thresholds.drawdown_mult_warn:
            flag("WARNING", "drawdown_exceeds_limit")

    return status, reasons


def format_human_readable(
    symbol: str,
    config_id: str,
    sweep_metrics: Dict[str, Optional[float]],
    live_metrics: Dict[str, float],
    status: str,
    reasons_details: List[str],
    *,
    window_trades: int,
    min_trades: int,
) -> str:
    lines = [f"Symbol: {symbol}", f"  Config: {config_id or 'N/A'}"]
    lines.append(
        f"  Trades (window): {live_metrics.get('num_trades', 0)} (min required: {min_trades})"
    )
    lines.append("  Sweep metrics:")
    lines.append(
        f"    win_rate: {sweep_metrics.get('win_rate', 0.0):.2f}"
        if sweep_metrics.get("win_rate") is not None
        else "    win_rate: n/a"
    )
    lines.append(
        f"    avg_pnl_pct: {sweep_metrics.get('avg_value', 0.0):.2f}"
        if sweep_metrics.get("avg_value") is not None
        else "    avg_pnl_pct: n/a"
    )
    lines.append(
        f"    max_drawdown: {sweep_metrics.get('max_drawdown', 0.0):.2f}"
        if sweep_metrics.get("max_drawdown") is not None
        else "    max_drawdown: n/a"
    )

    lines.append(f"  Live metrics (last {window_trades} trades):")
    lines.append(f"    win_rate: {live_metrics.get('win_rate', 0.0):.2f}")
    lines.append(f"    avg_pnl_pct: {live_metrics.get('avg_value', 0.0):.2f}")
    lines.append(f"    median_pnl_pct: {live_metrics.get('median_value', 0.0):.2f}")
    lines.append(f"    max_drawdown: {live_metrics.get('max_drawdown', 0.0):.2f}")
    lines.append(f"  Status: {status}")
    if reasons_details:
        lines.append("  Reasons:")
        for reason in reasons_details:
            lines.append(f"    - {reason}")
    return "\n".join(lines)


def _build_reason_details(
    sweep_metrics: Dict[str, Optional[float]],
    live_metrics: Dict[str, float],
    thresholds: Thresholds,
) -> List[str]:
    details: List[str] = []
    sweep_win = sweep_metrics.get("win_rate")
    live_win = live_metrics.get("win_rate")
    if sweep_win is not None and live_win is not None:
        drop = sweep_win - live_win
        if drop >= thresholds.win_rate_drop_warn:
            details.append(
                f"win_rate dropped by {drop:.2f} (warn {thresholds.win_rate_drop_warn:.2f}, fail {thresholds.win_rate_drop_fail:.2f})"
            )

    sweep_avg = sweep_metrics.get("avg_value")
    live_avg = live_metrics.get("avg_value")
    if sweep_avg is not None and live_avg is not None:
        gap = sweep_avg - live_avg
        if gap >= thresholds.pnl_pct_gap_warn:
            details.append(
                f"avg_pnl_pct below sweep by {gap:.2f} (warn {thresholds.pnl_pct_gap_warn:.2f}, fail {thresholds.pnl_pct_gap_fail:.2f})"
            )
        if live_avg < 0:
            details.append(f"avg_pnl_pct is negative ({live_avg:.2f})")

    sweep_dd = sweep_metrics.get("max_drawdown")
    live_dd = live_metrics.get("max_drawdown")
    if sweep_dd is not None and live_dd is not None and sweep_dd != 0:
        dd_mult = abs(live_dd) / max(abs(sweep_dd), 1e-9)
        if dd_mult >= thresholds.drawdown_mult_warn:
            details.append(
                f"max_drawdown is {dd_mult:.2f}x sweep (warn {thresholds.drawdown_mult_warn:.2f}, fail {thresholds.drawdown_mult_fail:.2f})"
            )
    return details


def assess_symbol(
    symbol: str,
    best_entry: Dict[str, Any],
    trades: List[ParsedTrade],
    *,
    metric: str,
    window_trades: int,
    min_trades: int,
    thresholds: Thresholds,
) -> Dict[str, Any]:
    metric_key = _map_metric_key(metric)
    sweep_metrics = extract_sweep_metrics(best_entry, metric_key=metric_key)

    symbol_trades = [t for t in trades if t.symbol == symbol]
    config_id = str(best_entry.get("config_id", "") or "")
    if config_id:
        symbol_trades = [t for t in symbol_trades if t.config_id == config_id]

    symbol_trades.sort(
        key=lambda t: (
            t.timestamp_close or t.timestamp_open or datetime.min,
            t.row_index,
        )
    )
    if window_trades and len(symbol_trades) > window_trades:
        symbol_trades = symbol_trades[-window_trades:]

    live_metrics = compute_live_metrics(symbol_trades, metric_key=metric_key)

    if live_metrics["num_trades"] < min_trades:
        return {
            "symbol": symbol,
            "config_id": config_id,
            "status": "INSUFFICIENT_DATA",
            "reasons": ["not_enough_trades"],
            "sweep_metrics": sweep_metrics,
            "live_metrics": {
                **live_metrics,
                "avg_pnl_pct": live_metrics["avg_value"],
                "median_pnl_pct": live_metrics["median_value"],
            },
        }

    status, reasons = evaluate_symbol_health(sweep_metrics, live_metrics, thresholds)
    reason_details = _build_reason_details(sweep_metrics, live_metrics, thresholds)

    return {
        "symbol": symbol,
        "config_id": config_id,
        "status": status,
        "reasons": reasons,
        "sweep_metrics": sweep_metrics,
        "live_metrics": {
            **live_metrics,
            "avg_pnl_pct": live_metrics["avg_value"],
            "median_pnl_pct": live_metrics["median_value"],
        },
        "reason_details": reason_details,
    }


def evaluate_symbols_health(
    best_configs_path: str,
    trades_csv_path: str,
    *,
    symbol_filter: Optional[List[str]] = None,
    window_trades: int = 100,
    min_trades: int = 30,
    metric: str = "pnl_pct",
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Evaluate health for symbols and return (mapping symbol -> assessment, meta)."""

    best_mapping, meta = load_best_configs(Path(best_configs_path))
    trades_rows = load_trades(Path(trades_csv_path))
    parsed_trades = parse_trades(trades_rows)

    symbols = symbol_filter or sorted(best_mapping.keys())
    symbols = [s.upper() for s in symbols]

    thresholds = Thresholds()
    results: Dict[str, Dict[str, Any]] = {}
    for symbol in symbols:
        best_entry = best_mapping.get(symbol)
        if not best_entry:
            results[symbol] = {
                "symbol": symbol,
                "config_id": "",
                "status": "INSUFFICIENT_DATA",
                "reasons": ["missing_best_config"],
                "sweep_metrics": {},
                "live_metrics": {},
                "reason_details": ["Best-config entry missing"],
            }
            continue

        results[symbol] = assess_symbol(
            symbol,
            best_entry,
            parsed_trades,
            metric=metric,
            window_trades=window_trades,
            min_trades=min_trades,
            thresholds=thresholds,
        )

    return results, meta


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Health check comparing live performance vs sweep best-config baselines."
    )
    parser.add_argument(
        "--best-configs-json", required=True, help="Path to best_configs.json"
    )
    parser.add_argument(
        "--trades-csv", required=True, help="Path to live trade log CSV"
    )
    parser.add_argument("--symbol", help="Optional symbol filter (e.g., BTCUSDT)")
    parser.add_argument(
        "--window-trades",
        type=int,
        default=100,
        help="Number of most recent trades per symbol to analyze (default: 100)",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=30,
        help="Minimum number of trades required to evaluate a symbol (default: 30)",
    )
    parser.add_argument(
        "--metric",
        type=str,
        default="pnl_pct",
        help="Metric used for comparison (default: pnl_pct)",
    )
    parser.add_argument(
        "--json-out",
        type=str,
        help="Optional path to write the machine-readable JSON summary.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    results_map, meta = evaluate_symbols_health(
        args.best_configs_json,
        args.trades_csv,
        symbol_filter=[args.symbol] if args.symbol else None,
        window_trades=args.window_trades,
        min_trades=args.min_trades,
        metric=args.metric,
    )

    results: List[Dict[str, Any]] = []
    for symbol in sorted(results_map.keys()):
        result = results_map[symbol]
        results.append(result)
        reasons_details = result.get("reason_details", [])
        human = format_human_readable(
            symbol,
            result.get("config_id", ""),
            result.get("sweep_metrics", {}),
            result.get("live_metrics", {}),
            result["status"],
            reasons_details,
            window_trades=args.window_trades,
            min_trades=args.min_trades,
        )
        print(human)
        print("-" * 60)

    if args.json_out:
        payload = {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "metric": args.metric,
            "window_trades": args.window_trades,
            "min_trades": args.min_trades,
            "symbols": [
                {
                    "symbol": result["symbol"],
                    "config_id": result.get("config_id"),
                    "status": result["status"],
                    "reasons": result.get("reasons", []),
                    "sweep_metrics": result.get("sweep_metrics", {}),
                    "live_metrics": result.get("live_metrics", {}),
                }
                for result in results
            ],
            "best_configs": meta,
        }
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))
        logger.info("Wrote health summary JSON to %s", out_path)

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
