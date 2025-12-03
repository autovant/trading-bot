from datetime import datetime, timedelta, timezone

from src.state.symbol_health_store import SymbolHealthStore, _format_iso


def test_initial_state_empty(tmp_path):
    store = SymbolHealthStore(tmp_path / "health.json")
    state = store.get_symbol_state("BTCUSDT")
    assert state["last_status"] is None
    assert state["blocked_until"] is None
    assert state["last_reasons"] == []


def test_update_and_reload(tmp_path):
    path = tmp_path / "health.json"
    store = SymbolHealthStore(path)
    evaluated_at = "2025-01-01T00:00:00Z"
    store.update_symbol_state(
        "ETHUSDT",
        status="WARNING",
        reasons=["drawdown"],
        blocked_until=None,
        evaluated_at=evaluated_at,
    )

    reloaded = SymbolHealthStore(path)
    state = reloaded.get_symbol_state("ETHUSDT")
    assert state["last_status"] == "WARNING"
    assert state["last_reasons"] == ["drawdown"]
    assert state["last_evaluated_at"] == evaluated_at


def test_is_blocked_and_multiplier(tmp_path):
    store = SymbolHealthStore(tmp_path / "health.json")
    now = datetime.now(timezone.utc)
    blocked_until = _format_iso(now + timedelta(minutes=5))
    store.update_symbol_state(
        "SOLUSDT",
        status="FAILING",
        reasons=["cooldown"],
        blocked_until=blocked_until,
    )
    assert store.is_blocked("SOLUSDT", now=now)
    assert store.get_effective_size_multiplier("SOLUSDT", warning_size_multiplier=0.5) == 0.0

    past_block = _format_iso(now - timedelta(minutes=1))
    store.update_symbol_state(
        "SOLUSDT",
        status="WARNING",
        reasons=["recovering"],
        blocked_until=past_block,
    )
    assert not store.is_blocked("SOLUSDT", now=now)
    assert store.get_effective_size_multiplier("SOLUSDT", warning_size_multiplier=0.5) == 0.5
