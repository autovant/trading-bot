from src.state.perps_state_store import (
    PerpsState,
    load_perps_state,
    save_perps_state,
)


def test_perps_state_round_trip(tmp_path):
    path = tmp_path / "perps_state.json"
    state = PerpsState(
        peak_equity=1234.5,
        daily_pnl_by_date={"2025-01-01": -12.0},
        consecutive_losses=2,
    )
    save_perps_state(path, state)
    loaded = load_perps_state(path)
    assert loaded == state


def test_load_missing_state(tmp_path):
    path = tmp_path / "missing.json"
    assert load_perps_state(path) is None


def test_load_malformed_state(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not-json}", encoding="utf-8")
    assert load_perps_state(path) is None
