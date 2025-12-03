from src.risk.risk_manager import RiskManager
from src.state.daily_pnl_store import DailyPnlStore


def test_risk_manager_blocks_when_open_risk_limit_exceeded():
    manager = RiskManager(
        starting_equity=1000.0,
        max_account_risk_pct=0.02,
        max_open_risk_pct=0.05,
        max_symbol_risk_pct=0.03,
    )

    allowed, reason = manager.can_open_new_position("BTCUSDT", 500.0, 0.01)
    assert allowed
    assert reason is None

    manager.register_open_position("BTCUSDT", 500.0, 0.01)

    allowed, reason = manager.can_open_new_position("BTCUSDT", 4000.0, 0.02)
    assert not allowed
    assert reason == "max_open_risk_pct"


def test_symbol_limit_enforced_independently():
    manager = RiskManager(
        starting_equity=1000.0,
        max_account_risk_pct=0.10,
        max_open_risk_pct=0.50,
        max_symbol_risk_pct=0.03,
    )

    manager.register_open_position("SOLUSDT", 800.0, 0.02)  # risk $16, well below account cap
    allowed, reason = manager.can_open_new_position("SOLUSDT", 1000.0, 0.02)

    assert not allowed
    assert reason == "max_symbol_risk_pct"


def test_daily_loss_stop_blocks_new_positions():
    manager = RiskManager(
        starting_equity=1000.0,
        max_account_risk_pct=0.05,
        max_open_risk_pct=0.50,
        max_symbol_risk_pct=0.50,
        max_daily_loss_usd=50.0,
    )

    manager.register_close_position("BTCUSDT", -60.0)

    allowed, reason = manager.can_open_new_position("ETHUSDT", 100.0, 0.01)
    assert not allowed
    assert reason in {"max_daily_loss_usd", "max_account_risk_pct"}


def test_daily_loss_persists_across_instances(tmp_path):
    store = DailyPnlStore(str(tmp_path / "pnl.json"))
    account_id = "zoomex-paper"

    manager = RiskManager(
        starting_equity=1000.0,
        max_account_risk_pct=0.10,
        max_open_risk_pct=0.50,
        max_symbol_risk_pct=0.50,
        max_daily_loss_usd=30.0,
        daily_pnl_store=store,
        account_id=account_id,
    )

    manager.register_close_position("BTCUSDT", -20.0)
    manager.register_close_position("ETHUSDT", -15.0)

    allowed, reason = manager.can_open_new_position("SOLUSDT", 100.0, 0.01)
    assert not allowed
    assert reason == "max_daily_loss_usd"

    # Recreate manager with same store to ensure persisted loss is respected
    manager2 = RiskManager(
        starting_equity=1000.0,
        max_account_risk_pct=0.10,
        max_open_risk_pct=0.50,
        max_symbol_risk_pct=0.50,
        max_daily_loss_usd=30.0,
        daily_pnl_store=store,
        account_id=account_id,
    )

    allowed2, reason2 = manager2.can_open_new_position("SOLUSDT", 100.0, 0.01)
    assert not allowed2
    assert reason2 == "max_daily_loss_usd"
