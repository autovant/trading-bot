from datetime import datetime, timedelta

import pytest

from src.database import DatabaseManager, PnLEntry


@pytest.mark.asyncio
async def test_aggregate_daily_pnl_rollup(tmp_path):
    db_path = tmp_path / "rollup.db"
    database = DatabaseManager(db_path)
    await database.initialize()

    base_timestamp = datetime.utcnow().replace(microsecond=0)
    entry_one = PnLEntry(
        symbol="BTCUSDT",
        trade_id="trade-1",
        realized_pnl=10.0,
        unrealized_pnl=1.5,
        commission=0.1,
        fees=0.2,
        funding=0.05,
        net_pnl=11.0,
        balance=1011.0,
        mode="paper",
        run_id="rollup-test",
        timestamp=base_timestamp,
    )
    entry_two = PnLEntry(
        symbol="BTCUSDT",
        trade_id="trade-2",
        realized_pnl=-4.0,
        unrealized_pnl=0.5,
        commission=0.05,
        fees=0.1,
        funding=0.02,
        net_pnl=-3.5,
        balance=1007.5,
        mode="paper",
        run_id="rollup-test",
        timestamp=base_timestamp + timedelta(minutes=30),
    )

    await database.add_pnl_entry(entry_one)
    await database.add_pnl_entry(entry_two)

    summaries = await database.aggregate_daily_pnl(days=1)
    assert summaries, "Expected rollup summary rows"
    summary = summaries[0]

    assert summary.trade_id.startswith("rollup-paper-rollup-test-")
    assert summary.realized_pnl == pytest.approx(6.0)
    assert summary.unrealized_pnl == pytest.approx(2.0)
    assert summary.commission == pytest.approx(0.15)
    assert summary.fees == pytest.approx(0.3)
    assert summary.funding == pytest.approx(0.07)
    assert summary.net_pnl == pytest.approx(7.5)
    assert summary.balance == pytest.approx(entry_two.balance)

    await database.add_pnl_entry(summary)
    history = await database.get_pnl_history(days=1)
    rollups = [row for row in history if row.trade_id.startswith("rollup-")]
    assert len(rollups) == 1

    await database.close()
