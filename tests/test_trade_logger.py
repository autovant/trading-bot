import csv
from datetime import datetime, timezone

from src.logging.trade_logger import TradeLogger


def _sample_trade(symbol: str = "BTCUSDT") -> dict:
    now = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    close = now.replace(minute=30)
    return {
        "timestamp_open": now,
        "timestamp_close": close,
        "symbol": symbol,
        "side": "LONG",
        "size": 1.0,
        "notional": 100.0,
        "entry_price": 100.0,
        "exit_price": 105.0,
        "realized_pnl": 5.0,
        "realized_pnl_pct": 0.05,
        "fees": 0.1,
        "config_id": "cfg-123",
        "strategy_name": "perps_trend_vwap",
        "account_equity_before": 1000.0,
        "account_equity_after": 1005.0,
        "risk_blocked_before_entry": False,
        "extra": {"orderId": "abc"},
    }


def test_trade_logger_writes_header(tmp_path):
    csv_path = tmp_path / "trades.csv"
    logger = TradeLogger(csv_path)

    logger.log_completed_trade(_sample_trade())

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert reader.fieldnames == TradeLogger.HEADERS
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[0]["realized_pnl"] == "5.0"


def test_trade_logger_appends_rows(tmp_path):
    csv_path = tmp_path / "trades.csv"
    logger = TradeLogger(csv_path)

    logger.log_completed_trade(_sample_trade("BTCUSDT"))
    logger.log_completed_trade(_sample_trade("ETHUSDT"))

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[1]["symbol"] == "ETHUSDT"
    assert rows[0]["timestamp_open"]
    assert rows[1]["timestamp_close"]


def test_trade_logger_handles_missing_optional_fields(tmp_path):
    csv_path = tmp_path / "trades.csv"
    logger = TradeLogger(csv_path)

    minimal_trade = {
        "timestamp_open": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "timestamp_close": datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
        "symbol": "SOLUSDT",
        "side": "LONG",
        "size": 2.0,
        "notional": 200.0,
        "entry_price": 100.0,
        "exit_price": 110.0,
        "realized_pnl": 20.0,
        "realized_pnl_pct": 0.10,
    }

    logger.log_completed_trade(minimal_trade)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)

    assert row["fees"] == "0.0"
    assert row["config_id"] == ""
    assert row["extra"] == ""
    assert row["risk_blocked_before_entry"] == ""
