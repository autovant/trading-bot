#!/usr/bin/env python3
"""
Analyze sweep summary JSON files and rank configs across sweeps.

The analyzer is intentionally minimal and depends only on the standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_summary_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load %s: %s", path, exc)
        return None

    schema_version = str(payload.get("schema_version", ""))
    if not schema_version.startswith("1."):
        logger.warning(
            "Skipping %s due to incompatible schema_version=%s", path, schema_version
        )
        return None
    return payload


def collect_config_entries(
    summaries: Iterable[Dict[str, Any]],
    *,
    metric: str,
    symbol_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for payload in summaries:
        sweep_id = payload.get("sweep_id")
        run_tag = payload.get("run_tag")
        configs = payload.get("configs_summary") or []
        for cfg in configs:
            symbol = cfg.get("symbol")
            if symbol_filter and symbol != symbol_filter:
                continue
            metrics = cfg.get("metrics") or {}
            metric_value = metrics.get(metric)
            if metric_value is None or not _is_number(metric_value):
                continue
            entries.append(
                {
                    "symbol": symbol,
                    "config_id": cfg.get("config_id"),
                    "params": cfg.get("params") or {},
                    "metrics": metrics,
                    "metric_value": metric_value,
                    "runtime_seconds": cfg.get("runtime_seconds"),
                    "early_stopped": bool(cfg.get("early_stopped")),
                    "sweep_id": sweep_id,
                    "run_tag": run_tag,
                }
            )
    return entries


def aggregate_configs(
    entries: Iterable[Dict[str, Any]],
    *,
    metric: str,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    aggregates: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for entry in entries:
        key = (entry["symbol"], entry["config_id"])
        agg = aggregates.get(key)
        metric_value = entry["metric_value"]
        num_trades = entry["metrics"].get("num_trades")
        metrics_used = list(entry["metrics"].keys())

        if agg is None:
            aggregates[key] = {
                "symbol": entry["symbol"],
                "config_id": entry["config_id"],
                "params": entry["params"],
                "metric_values": [metric_value],
                "metric": metric,
                "num_runs": 1,
                "total_trades": num_trades if _is_number(num_trades) else 0,
                "any_early_stopped": entry["early_stopped"],
                "metrics_used": metrics_used,
            }
            continue

        agg["metric_values"].append(metric_value)
        agg["num_runs"] += 1
        if _is_number(num_trades):
            agg["total_trades"] += num_trades
        agg["any_early_stopped"] = agg["any_early_stopped"] or entry["early_stopped"]
        # Prefer first params; keep existing
        agg["metrics_used"] = sorted(set(agg["metrics_used"]).union(metrics_used))

    for agg in aggregates.values():
        values = agg["metric_values"]
        agg["metric_mean"] = mean(values)
        agg["metric_median"] = median(values)
        agg["metric_min"] = min(values)
        agg["metric_max"] = max(values)
        # drop raw list before returning to keep payload small
        agg.pop("metric_values", None)
    return aggregates


def find_summary_files(
    summaries: Optional[List[str]], summaries_dir: str
) -> List[Path]:
    if summaries:
        return [Path(p) for p in summaries]
    base = Path(summaries_dir)
    if not base.exists():
        return []
    return sorted(base.rglob("sweep_summary*.json"))


def render_report(
    aggregates: Dict[Tuple[str, str], Dict[str, Any]], metric: str, top_n: int
) -> str:
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for agg in aggregates.values():
        by_symbol.setdefault(agg["symbol"], []).append(agg)

    lines: List[str] = []
    lines.append(f"Analysis of {len(aggregates)} configs (metric: {metric})")
    for symbol, configs in sorted(by_symbol.items()):
        lines.append(f"\n=== SYMBOL: {symbol} ===")
        configs.sort(key=lambda c: c["metric_mean"], reverse=True)
        for idx, cfg in enumerate(configs[:top_n], start=1):
            lines.append(
                f"{idx:>2} {cfg['config_id']} "
                f"mean={cfg['metric_mean']:.4f} max={cfg['metric_max']:.4f} "
                f"runs={cfg['num_runs']} trades={cfg['total_trades']} "
                f"early_stop={cfg['any_early_stopped']}"
            )
    return "\n".join(lines)


def select_best_configs(
    aggregates: Dict[Tuple[str, str], Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for agg in aggregates.values():
        by_symbol.setdefault(agg["symbol"], []).append(agg)

    best: Dict[str, Dict[str, Any]] = {}
    for symbol, configs in by_symbol.items():
        configs_sorted = sorted(
            configs,
            key=lambda c: (c["metric_mean"], c["metric_max"], c["num_runs"]),
            reverse=True,
        )
        if configs_sorted:
            best[symbol] = configs_sorted[0]
    return best


def write_best_json(best: Dict[str, Dict[str, Any]], metric: str, path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "metric": metric,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "symbols": [
            {
                "symbol": cfg["symbol"],
                "config_id": cfg["config_id"],
                "metric_mean": cfg["metric_mean"],
                "metric_max": cfg["metric_max"],
                "num_runs": cfg["num_runs"],
                "total_trades": cfg["total_trades"],
                "any_early_stopped": cfg["any_early_stopped"],
                "params": cfg["params"],
            }
            for cfg in best.values()
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    logger.info("Wrote best-config JSON to %s", path)


def write_csv(
    aggregates: Dict[Tuple[str, str], Dict[str, Any]], metric: str, csv_path: Path
) -> None:
    fieldnames = [
        "symbol",
        "config_id",
        "metric",
        "metric_mean",
        "metric_median",
        "metric_min",
        "metric_max",
        "num_runs",
        "total_trades",
        "any_early_stopped",
        "params_json",
        "metrics_used",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for agg in aggregates.values():
            writer.writerow(
                {
                    "symbol": agg["symbol"],
                    "config_id": agg["config_id"],
                    "metric": metric,
                    "metric_mean": agg["metric_mean"],
                    "metric_median": agg["metric_median"],
                    "metric_min": agg["metric_min"],
                    "metric_max": agg["metric_max"],
                    "num_runs": agg["num_runs"],
                    "total_trades": agg["total_trades"],
                    "any_early_stopped": agg["any_early_stopped"],
                    "params_json": json.dumps(agg["params"], sort_keys=True),
                    "metrics_used": ",".join(agg.get("metrics_used", [])),
                }
            )


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze sweep summary JSON files and rank configs."
    )
    parser.add_argument(
        "--summaries-dir",
        type=str,
        default="results/backtests",
        help="Directory to search for sweep summaries.",
    )
    parser.add_argument(
        "--summaries", nargs="*", help="Explicit list of summary JSON files to include."
    )
    parser.add_argument("--symbol", type=str, help="Restrict analysis to this symbol.")
    parser.add_argument(
        "--metric",
        type=str,
        default="pnl",
        help="Metric key inside metrics to rank by.",
    )
    parser.add_argument(
        "--top-n", type=int, default=10, help="How many configs to show per symbol."
    )
    parser.add_argument("--csv-out", type=str, help="Optional CSV output path.")
    parser.add_argument(
        "--best-json", type=str, help="Optional best-config JSON output path."
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    files = find_summary_files(args.summaries, args.summaries_dir)
    if not files:
        logger.error("No summary files found (dir=%s).", args.summaries_dir)
        return 1

    summaries: List[Dict[str, Any]] = []
    for path in files:
        payload = load_summary_file(path)
        if payload is not None:
            summaries.append(payload)
    if not summaries:
        logger.error("All summary files were skipped; nothing to analyze.")
        return 1

    entries = collect_config_entries(
        summaries, metric=args.metric, symbol_filter=args.symbol
    )
    if not entries:
        logger.error(
            "No configs found matching the metric '%s'%s.",
            args.metric,
            f" for symbol {args.symbol}" if args.symbol else "",
        )
        return 1

    aggregates = aggregate_configs(entries, metric=args.metric)
    report = render_report(aggregates, metric=args.metric, top_n=args.top_n)
    print(report)

    if args.csv_out:
        write_csv(aggregates, metric=args.metric, csv_path=Path(args.csv_out))
        logger.info("Wrote CSV to %s", args.csv_out)

    if args.best_json:
        best = select_best_configs(aggregates)
        if not best:
            logger.error("No configs available to select best entries.")
            return 1
        write_best_json(best, metric=args.metric, path=Path(args.best_json))

    logger.info(
        "Processed %d summaries, aggregated %d configs.",
        len(summaries),
        len(aggregates),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
