from src.state.daily_pnl_store import DailyPnlStore


def test_daily_pnl_store_persists_and_accumulates(tmp_path):
    path = tmp_path / "pnl.json"
    store = DailyPnlStore(str(path))

    total = store.update_pnl("acct1", "2025-01-01", -50.0)
    assert total == -50.0

    total = store.update_pnl("acct1", "2025-01-01", 10.0)
    assert total == -40.0

    reloaded = DailyPnlStore(str(path))
    assert reloaded.get_pnl("acct1", "2025-01-01") == -40.0


def test_daily_pnl_store_defaults(tmp_path):
    path = tmp_path / "missing.json"
    store = DailyPnlStore(str(path))
    assert store.get_pnl("acct2", "2025-02-01") == 0.0
