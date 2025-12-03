from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import run_bot
from run_bot import TradingBot
from src.state.symbol_health_store import _format_iso


class DummyPerpsService:
    def __init__(self, symbol: str = "BTCUSDT"):
        self.config = SimpleNamespace(symbol=symbol)
        self.symbol_health_store = None
        self.warning_size_multiplier = None
        self.attempts = 0

    def set_symbol_health_store(self, store, warning_size_multiplier=None):
        self.symbol_health_store = store
        self.warning_size_multiplier = warning_size_multiplier

    async def run_cycle(self):
        if self.symbol_health_store and self.symbol_health_store.is_blocked(self.config.symbol):
            return
        self.attempts += 1


def test_runtime_health_monitor_starts(monkeypatch, tmp_path):
    calls = {}

    def fake_start(
        symbols,
        best_configs_path,
        trades_csv_path,
        symbol_health_store,
        interval_seconds,
        window_trades,
        min_trades,
        metric,
        cooldown_minutes,
        logger,
        stop_event=None,
        skip_if_unchanged_trades=False,
        cooldown_backoff_multiplier=1.0,
    ):
        calls["symbols"] = symbols
        calls["best_path"] = best_configs_path
        calls["trades_path"] = trades_csv_path
        calls["store"] = symbol_health_store
        calls["skip_if_unchanged_trades"] = skip_if_unchanged_trades
        calls["cooldown_backoff_multiplier"] = cooldown_backoff_multiplier
        return SimpleNamespace()

    monkeypatch.setattr(run_bot, "start_runtime_health_monitor", fake_start)

    runtime_settings = {
        "enabled": True,
        "interval_seconds": 1,
        "window_trades": 10,
        "min_trades": 1,
        "metric": "pnl_pct",
        "cooldown_minutes": 5,
        "warning_size_multiplier": 0.25,
        "skip_if_unchanged_trades": True,
        "cooldown_backoff_multiplier": 2.0,
        "best_configs_path": str(tmp_path / "best.json"),
        "trades_csv": str(tmp_path / "trades.csv"),
        "store_path": str(tmp_path / "health.json"),
    }

    bot = TradingBot(
        "paper",
        "config.yaml",
        {},
        best_configs_path="best.json",
        trade_log_csv=str(tmp_path / "trades.csv"),
        health_settings={},
        risk_limits={
            "max_account_risk_pct": 0.02,
            "max_open_risk_pct": 0.05,
            "max_symbol_risk_pct": 0.03,
            "max_daily_loss_usd": None,
        },
        runtime_health_settings=runtime_settings,
    )
    bot.perps_service = DummyPerpsService()
    bot.trade_logger = SimpleNamespace(csv_path=tmp_path / "trades.csv")
    bot.daily_pnl_store_path = str(tmp_path / "daily.json")

    bot._attach_symbol_health_store()
    bot._maybe_start_runtime_health_monitor()

    assert calls["symbols"] == ["BTCUSDT"]
    assert calls["best_path"] == runtime_settings["best_configs_path"]
    assert calls["trades_path"] == runtime_settings["trades_csv"]
    assert bot.perps_service.symbol_health_store is bot.symbol_health_store
    assert bot.perps_service.warning_size_multiplier == runtime_settings["warning_size_multiplier"]
    assert calls["skip_if_unchanged_trades"] is True
    assert calls["cooldown_backoff_multiplier"] == 2.0


@pytest.mark.asyncio
async def test_runtime_health_block_prevents_trades(tmp_path):
    runtime_settings = {
        "enabled": True,
        "warning_size_multiplier": 0.5,
        "store_path": str(tmp_path / "health.json"),
    }
    bot = TradingBot(
        "paper",
        "config.yaml",
        {},
        trade_log_csv=str(tmp_path / "trades.csv"),
        health_settings={},
        runtime_health_settings=runtime_settings,
    )
    service = DummyPerpsService()
    bot.perps_service = service
    bot.daily_pnl_store_path = str(tmp_path / "daily.json")

    bot._attach_symbol_health_store()
    blocked_until = _format_iso(datetime.now(timezone.utc) + timedelta(minutes=10))
    bot.symbol_health_store.update_symbol_state(
        "BTCUSDT",
        status="FAILING",
        reasons=["cooldown"],
        blocked_until=blocked_until,
    )

    await service.run_cycle()
    assert service.attempts == 0

    bot.symbol_health_store.update_symbol_state(
        "BTCUSDT",
        status="OK",
        reasons=[],
        blocked_until=None,
    )

    await service.run_cycle()
    assert service.attempts == 1
