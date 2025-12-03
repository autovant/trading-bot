from types import SimpleNamespace

import pytest

import run_bot
from run_bot import TradingBot


def _build_bot(health_min_status="WARNING", strict=False):
    health_settings = {
        "enabled": True,
        "best_configs_path": "best.json",
        "trades_csv": "trades.csv",
        "window_trades": 10,
        "min_trades": 2,
        "metric": "pnl_pct",
        "min_status": health_min_status,
        "strict": strict,
    }
    bot = TradingBot(
        "paper",
        "config.yaml",
        {},
        best_configs_path="best.json",
        risk_limits={"max_account_risk_pct": 0.02, "max_open_risk_pct": 0.05, "max_symbol_risk_pct": 0.03},
        trade_log_csv="trades.csv",
        health_settings=health_settings,
    )
    bot.config = SimpleNamespace(perps=SimpleNamespace(symbol="BTCUSDT", exchange="zoomex"))
    bot.overrides = {}
    return bot


def test_health_gate_allows_ok(monkeypatch):
    bot = _build_bot()
    monkeypatch.setattr(
        run_bot,
        "evaluate_symbols_health",
        lambda *args, **kwargs: ({"BTCUSDT": {"status": "OK", "reasons": []}}, {}),
    )
    bot._maybe_run_health_gating()


def test_health_gate_blocks_non_strict(monkeypatch):
    bot = _build_bot(health_min_status="WARNING", strict=False)
    monkeypatch.setattr(
        run_bot,
        "evaluate_symbols_health",
        lambda *args, **kwargs: ({"BTCUSDT": {"status": "FAILING", "reasons": ["bad"]}}, {}),
    )

    with pytest.raises(SystemExit) as excinfo:
        bot._maybe_run_health_gating()
    assert excinfo.value.code == 0


def test_health_gate_blocks_strict(monkeypatch):
    bot = _build_bot(health_min_status="OK", strict=True)
    monkeypatch.setattr(
        run_bot,
        "evaluate_symbols_health",
        lambda *args, **kwargs: ({"BTCUSDT": {"status": "WARNING", "reasons": ["gap"]}}, {}),
    )

    with pytest.raises(SystemExit) as excinfo:
        bot._maybe_run_health_gating()
    assert excinfo.value.code == 1
