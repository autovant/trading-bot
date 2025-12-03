import json
import logging
from types import SimpleNamespace

from run_bot import TradingBot
from src.config import PerpsConfig


def _write_best_configs(tmp_path, *, symbol="BTCUSDT", params=None):
    payload = {
        "schema_version": "1.0",
        "metric": "sharpe",
        "generated_at": "2025-01-01T00:00:00Z",
        "symbols": [
            {
                "symbol": symbol,
                "config_id": f"{symbol}-cfg",
                "metric_mean": 1.23,
                "metric_max": 1.5,
                "num_runs": 2,
                "total_trades": 10,
                "any_early_stopped": False,
                "params": params or {},
            }
        ],
    }
    path = tmp_path / "best_configs.json"
    path.write_text(json.dumps(payload))
    return path


def test_best_configs_merge_overrides_params_and_preserves_defaults(tmp_path):
    best_path = _write_best_configs(
        tmp_path, params={"riskPct": 0.02, "atrStopMultiple": 2.5}
    )

    bot = TradingBot("paper", "config.yaml", {}, best_configs_path=str(best_path))
    base_perps = PerpsConfig(
        symbol="BTCUSDT",
        riskPct=0.005,
        atrStopMultiple=1.5,
        tp2Multiple=2.75,
    )
    bot.config = SimpleNamespace(perps=base_perps)

    bot._maybe_apply_best_configs()

    assert bot.config.perps.riskPct == 0.02
    assert bot.config.perps.atrStopMultiple == 2.5
    # Unspecified params remain untouched
    assert bot.config.perps.tp2Multiple == 2.75


def test_missing_symbol_warns_and_falls_back(tmp_path, caplog):
    best_path = _write_best_configs(
        tmp_path, symbol="ETHUSDT", params={"riskPct": 0.01}
    )

    bot = TradingBot(
        "paper",
        "config.yaml",
        {"symbol": "BTCUSDT"},
        best_configs_path=str(best_path),
    )
    base_perps = PerpsConfig(symbol="BTCUSDT", riskPct=0.0075)
    bot.config = SimpleNamespace(perps=base_perps)

    with caplog.at_level(logging.WARNING):
        bot._maybe_apply_best_configs()

    assert "no best-config entry found" in caplog.text
    assert bot.config.perps.riskPct == 0.0075


def test_no_best_configs_flag_keeps_config_unchanged():
    bot = TradingBot("paper", "config.yaml", {}, best_configs_path=None)
    base_perps = PerpsConfig(symbol="BTCUSDT", riskPct=0.004)
    bot.config = SimpleNamespace(perps=base_perps)

    bot._maybe_apply_best_configs()

    assert bot.config.perps.riskPct == 0.004
