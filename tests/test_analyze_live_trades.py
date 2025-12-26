import csv
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.app_logging.trade_logger import TradeLogger
from tools.analyze_live_trades import analyze_trades, load_trades


def _write_sample_trades(tmp_path):
    csv_path = tmp_path / "trades.csv"

    base = {field: "" for field in TradeLogger.HEADERS}

    rows = []
    start_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    rows.append(
        {
            **base,
            "timestamp_open": start_time.isoformat(),
            "timestamp_close": (start_time + timedelta(minutes=10)).isoformat(),
            "symbol": "BTCUSDT",
            "side": "LONG",
            "size": "1",
            "realized_pnl": "10",
            "realized_pnl_pct": "0.01",
        }
    )
    rows.append(
        {
            **base,
            "timestamp_open": (start_time + timedelta(hours=1)).isoformat(),
            "timestamp_close": (
                start_time + timedelta(hours=1, minutes=20)
            ).isoformat(),
            "symbol": "BTCUSDT",
            "side": "LONG",
            "size": "1",
            "realized_pnl": "-20",
            "realized_pnl_pct": "-0.02",
        }
    )
    rows.append(
        {
            **base,
            "timestamp_open": (start_time + timedelta(hours=2)).isoformat(),
            "timestamp_close": (start_time + timedelta(hours=2, minutes=5)).isoformat(),
            "symbol": "BTCUSDT",
            "side": "LONG",
            "size": "1",
            "realized_pnl": "30",
            "realized_pnl_pct": "0.03",
        }
    )
    rows.append(
        {
            **base,
            "timestamp_open": (start_time + timedelta(hours=3)).isoformat(),
            "timestamp_close": (
                start_time + timedelta(hours=3, minutes=15)
            ).isoformat(),
            "symbol": "ETHUSDT",
            "side": "LONG",
            "size": "2",
            "realized_pnl": "50",
            "realized_pnl_pct": "0.05",
        }
    )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TradeLogger.HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return csv_path


def test_analyze_trades_basic(tmp_path):
    csv_path = _write_sample_trades(tmp_path)
    trades = load_trades(csv_path)

    stats = analyze_trades(
        trades, symbol="BTCUSDT", metric="pnl_pct", window_trades=100
    )

    assert stats["trades"] == 3
    assert stats["win_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert stats["avg_metric"] == pytest.approx((0.01 - 0.02 + 0.03) / 3, rel=1e-6)
    assert stats["median_metric"] == pytest.approx(0.01, rel=1e-6)
    assert stats["max_drawdown"] == pytest.approx(-0.02, rel=1e-6)
    assert stats["avg_duration_minutes"] == pytest.approx(11.666, rel=1e-3)


def test_analyze_trades_symbol_filter(tmp_path):
    csv_path = _write_sample_trades(tmp_path)
    trades = load_trades(csv_path)

    stats = analyze_trades(
        trades, symbol="ETHUSDT", metric="realized_pnl", window_trades=10
    )

    assert stats["trades"] == 1
    assert stats["win_rate"] == 1.0
    assert stats["avg_metric"] == 50.0
    assert stats["median_metric"] == 50.0
    assert stats["max_drawdown"] == 0.0


def test_cli_smoke_run(tmp_path):
    csv_path = _write_sample_trades(tmp_path)
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "tools/analyze_live_trades.py",
            "--trades-csv",
            str(csv_path),
            "--symbol",
            "BTCUSDT",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Trades: 3" in result.stdout
