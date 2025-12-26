from pathlib import Path

import pandas as pd
import pytest

from tools import fetch_history, fetch_history_all


def _dummy_df(start_ms: int) -> pd.DataFrame:
    idx = pd.to_datetime(
        [start_ms, start_ms + 5 * 60 * 1000],
        unit="ms",
        utc=True,
    )
    df = pd.DataFrame(
        {
            "open": [10.0, 10.5],
            "high": [10.6, 10.8],
            "low": [9.9, 10.3],
            "close": [10.4, 10.6],
            "volume": [100.0, 120.0],
        },
        index=idx,
    )
    df.index.name = "start"
    return df


@pytest.mark.asyncio
async def test_fetch_history_writes_and_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls = {"count": 0}

    async def fake_get_klines(
        self, symbol, interval="5", limit=300, start=None, end=None
    ):
        # Stop once cursor advances beyond the end of the requested window.
        if start and start > fetch_history._to_ms("2023-01-01T00:20:00Z"):
            return pd.DataFrame(
                columns=["start", "open", "high", "low", "close", "volume"]
            )
        calls["count"] += 1
        return _dummy_df(int(start))

    monkeypatch.setattr(
        fetch_history.ZoomexV3Client, "get_klines", fake_get_klines, raising=False
    )

    output = tmp_path / "SOLUSDT_5m.csv"
    cfg = fetch_history.FetchConfig(
        symbol="SOLUSDT",
        interval="5",
        start="2023-01-01",
        end="2023-01-01T00:20:00Z",
        output=output,
    )

    await fetch_history.run_fetch(cfg)
    first = pd.read_csv(output)
    assert list(first.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert len(first) > 0
    assert calls["count"] > 0

    await fetch_history.run_fetch(cfg)
    second = pd.read_csv(output)
    assert len(second) == len(first)  # deduped merge, no double counting


@pytest.mark.asyncio
async def test_fetch_history_all_invokes_fetcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    called = []

    async def fake_run_fetch(cfg):
        called.append(cfg.symbol)
        path = tmp_path / f"{cfg.symbol}_{cfg.interval}m.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("timestamp,open,high,low,close,volume\n")
        return path

    monkeypatch.setattr(fetch_history_all, "run_fetch", fake_run_fetch)

    outputs = await fetch_history_all.fetch_all(
        ["SOLUSDT", "ETHUSDT"],
        start="2023-01-01",
        end="2023-01-02",
        interval="5",
        base_url=None,
        testnet=False,
        limit=1000,
        sleep_seconds=0.0,
    )

    assert set(called) == {"SOLUSDT", "ETHUSDT"}
    assert len(outputs) == 2
    for path in outputs:
        assert path.exists()
