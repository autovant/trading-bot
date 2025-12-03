import csv
import json
import os
import sys
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.logging.trade_logger import TradeLogger
from tools.health_check_configs import (
    Thresholds,
    assess_symbol,
    evaluate_symbol_health,
    evaluate_symbols_health,
    load_best_configs,
    load_trades,
    parse_trades,
)


def test_evaluate_symbol_health_ok_status():
    sweep = {"win_rate": 0.6, "avg_value": 0.3, "max_drawdown": -0.05}
    live = {"win_rate": 0.55, "avg_value": 0.15, "max_drawdown": -0.05}

    status, reasons = evaluate_symbol_health(sweep, live, Thresholds())

    assert status == "OK"
    assert reasons == []


def test_evaluate_symbol_health_warning_and_fail():
    thresholds = Thresholds()
    sweep = {"win_rate": 0.65, "avg_value": 0.4, "max_drawdown": -0.05}
    live_warn = {"win_rate": 0.46, "avg_value": 0.25, "max_drawdown": -0.06}
    live_fail = {"win_rate": 0.3, "avg_value": -0.1, "max_drawdown": -0.12}

    status_warn, reasons_warn = evaluate_symbol_health(sweep, live_warn, thresholds)
    status_fail, reasons_fail = evaluate_symbol_health(sweep, live_fail, thresholds)

    assert status_warn == "WARNING"
    assert "win_rate_drop" in reasons_warn

    assert status_fail == "FAILING"
    assert "win_rate_drop" in reasons_fail
    assert "avg_pnl_gap" in reasons_fail
    assert "negative_avg_pnl" in reasons_fail
    assert "drawdown_exceeds_limit" in reasons_fail


def _write_best_configs(tmp_path: Path, *, symbol: str = "BTCUSDT", config_id: str = "cfg-best") -> Path:
    payload = {
        "schema_version": "1.0",
        "metric": "pnl_pct",
        "generated_at": "2025-01-01T00:00:00Z",
        "symbols": [
            {
                "symbol": symbol,
                "config_id": config_id,
                "metrics": {
                    "win_rate": 0.7,
                    "pnl_pct": 0.4,
                    "max_drawdown": -0.05,
                    "num_trades": 200,
                },
                "params": {"riskPct": 0.01},
            }
        ],
    }
    path = tmp_path / "best_configs.json"
    path.write_text(json.dumps(payload))
    return path


def _write_trade_csv(tmp_path: Path, *, symbol: str = "BTCUSDT", config_id: str = "cfg-best") -> Path:
    csv_path = tmp_path / "trades.csv"
    base_time = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    values = [-0.05, 0.02, -0.07, -0.08, -0.1, 0.1, -0.15, -0.05, -0.05, -0.02]

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TradeLogger.HEADERS)
        writer.writeheader()
        for idx, value in enumerate(values):
            writer.writerow(
                {
                    "timestamp_open": (base_time + timedelta(minutes=idx * 5)).isoformat(),
                    "timestamp_close": (base_time + timedelta(minutes=idx * 5 + 3)).isoformat(),
                    "symbol": symbol,
                    "side": "LONG",
                    "size": "1",
                    "realized_pnl": value * 100,  # arbitrary scaling
                    "realized_pnl_pct": value,
                    "config_id": config_id,
                }
            )
    return csv_path


def test_assess_symbol_integration(tmp_path: Path):
    best_path = _write_best_configs(tmp_path)
    trades_path = _write_trade_csv(tmp_path)

    best_mapping, _ = load_best_configs(best_path)
    trades_rows = load_trades(trades_path)
    parsed_trades = parse_trades(trades_rows)

    result = assess_symbol(
        "BTCUSDT",
        best_mapping["BTCUSDT"],
        parsed_trades,
        metric="pnl_pct",
        window_trades=50,
        min_trades=5,
        thresholds=Thresholds(),
    )

    assert result["status"] == "FAILING"
    assert "win_rate_drop" in result["reasons"]
    assert "avg_pnl_gap" in result["reasons"]
    assert "drawdown_exceeds_limit" in result["reasons"]
    assert result["live_metrics"]["num_trades"] == 10


def test_evaluate_symbols_health_returns_mapping(tmp_path: Path):
    best_path = _write_best_configs(tmp_path)
    trades_path = _write_trade_csv(tmp_path)

    results, meta = evaluate_symbols_health(
        str(best_path),
        str(trades_path),
        window_trades=20,
        min_trades=5,
        metric="pnl_pct",
    )

    assert meta["metric"] == "pnl_pct"
    assert "BTCUSDT" in results
    assert results["BTCUSDT"]["status"] == "FAILING"


def test_cli_smoke(tmp_path: Path):
    best_path = _write_best_configs(tmp_path)
    trades_path = _write_trade_csv(tmp_path)

    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.health_check_configs",
            "--best-configs-json",
            str(best_path),
            "--trades-csv",
            str(trades_path),
            "--window-trades",
            "20",
            "--min-trades",
            "5",
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=env,
    )
    assert result.returncode == 0
    assert "Symbol: BTCUSDT" in result.stdout
