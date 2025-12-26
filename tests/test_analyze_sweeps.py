import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.analyze_sweeps import (
    aggregate_configs,
    collect_config_entries,
    load_summary_file,
    select_best_configs,
)


def _write_summary(
    tmp_dir: Path,
    filename: str,
    metric_value: float,
    *,
    symbol: str = "BTCUSDT",
    config_id: str = "cfg1",
    metric_name: str = "pnl",
    num_trades: int = 5,
):
    payload = {
        "schema_version": "1.1",
        "sweep_id": "sweep-1",
        "run_tag": "test",
        "symbols": [symbol],
        "configs_summary": [
            {
                "symbol": symbol,
                "config_id": config_id,
                "params": {"key": "value"},
                "metrics": {metric_name: metric_value, "num_trades": num_trades},
                "runtime_seconds": 0.1,
                "early_stopped": False,
            }
        ],
    }
    path = tmp_dir / filename
    path.write_text(json.dumps(payload))
    return path


def test_basic_aggregation(tmp_path: Path):
    summaries = [
        _write_summary(tmp_path, "a.json", 10.0, num_trades=3),
        _write_summary(tmp_path, "b.json", 20.0, num_trades=4),
    ]

    payloads = [
        p for p in (load_summary_file(path) for path in summaries) if p is not None
    ]
    entries = collect_config_entries(payloads, metric="pnl")
    aggregates = aggregate_configs(entries, metric="pnl")

    assert len(aggregates) == 1
    agg = list(aggregates.values())[0]
    assert agg["metric_mean"] == pytest.approx(15.0)
    assert agg["metric_max"] == pytest.approx(20.0)
    assert agg["num_runs"] == 2
    assert agg["total_trades"] == 7


def test_metric_filter_skips_null(tmp_path: Path):
    with_null = {
        "schema_version": "1.1",
        "sweep_id": "sweep-2",
        "run_tag": None,
        "symbols": ["BTCUSDT"],
        "configs_summary": [
            {
                "symbol": "BTCUSDT",
                "config_id": "cfg1",
                "params": {},
                "metrics": {"sharpe": None, "num_trades": 2},
                "runtime_seconds": 0.1,
                "early_stopped": False,
            },
            {
                "symbol": "BTCUSDT",
                "config_id": "cfg2",
                "params": {},
                "metrics": {"sharpe": 1.2, "num_trades": 3},
                "runtime_seconds": 0.2,
                "early_stopped": False,
            },
        ],
    }

    entries = collect_config_entries([with_null], metric="sharpe")
    assert len(entries) == 1
    assert entries[0]["config_id"] == "cfg2"


def test_cli_smoke(tmp_path: Path):
    summary_path = _write_summary(tmp_path, "cli.json", 12.5)
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.analyze_sweeps",
            "--summaries",
            str(summary_path),
            "--metric",
            "pnl",
            "--top-n",
            "5",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path.cwd(),
    )
    assert result.returncode == 0
    assert "Analysis of" in result.stdout
    assert "cfg1" in result.stdout


def test_select_best_configs_tiebreakers():
    aggregates = {
        ("BTCUSDT", "A"): {
            "symbol": "BTCUSDT",
            "config_id": "A",
            "params": {},
            "metric_mean": 1.0,
            "metric_max": 1.5,
            "num_runs": 2,
            "total_trades": 10,
            "any_early_stopped": False,
        },
        ("BTCUSDT", "B"): {
            "symbol": "BTCUSDT",
            "config_id": "B",
            "params": {},
            "metric_mean": 1.0,
            "metric_max": 1.5,
            "num_runs": 3,
            "total_trades": 12,
            "any_early_stopped": False,
        },
        ("BTCUSDT", "C"): {
            "symbol": "BTCUSDT",
            "config_id": "C",
            "params": {},
            "metric_mean": 1.1,
            "metric_max": 1.4,
            "num_runs": 1,
            "total_trades": 8,
            "any_early_stopped": False,
        },
    }

    best = select_best_configs(aggregates)
    assert best["BTCUSDT"]["config_id"] == "C"


def test_best_json_written(tmp_path: Path):
    summary_path = _write_summary(tmp_path, "best.json", 9.9, config_id="best1")
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    best_json = tmp_path / "out" / "best.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.analyze_sweeps",
            "--summaries",
            str(summary_path),
            "--metric",
            "pnl",
            "--best-json",
            str(best_json),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path.cwd(),
    )
    assert result.returncode == 0
    assert best_json.exists()
    payload = json.loads(best_json.read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["metric"] == "pnl"
    assert payload["symbols"][0]["config_id"] == "best1"
    assert payload["symbols"][0]["metric_mean"] == pytest.approx(9.9)


def test_best_json_not_written_when_no_configs(tmp_path: Path):
    payload = {
        "schema_version": "1.1",
        "sweep_id": "sweep-null",
        "symbols": ["BTCUSDT"],
        "configs_summary": [
            {
                "symbol": "BTCUSDT",
                "config_id": "cfg-null",
                "params": {},
                "metrics": {"pnl": None},
                "runtime_seconds": 0.1,
                "early_stopped": False,
            }
        ],
    }
    summary_path = tmp_path / "null.json"
    summary_path.write_text(json.dumps(payload))

    best_json = tmp_path / "out" / "best.json"
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.analyze_sweeps",
            "--summaries",
            str(summary_path),
            "--metric",
            "pnl",
            "--best-json",
            str(best_json),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path.cwd(),
    )
    assert result.returncode != 0
    assert not best_json.exists()
