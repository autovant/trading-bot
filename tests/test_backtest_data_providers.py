from pathlib import Path

import pandas as pd
import pytest

from src.exchanges import zoomex_v3
from tools.backtest_perps import CsvDataProvider, ZoomexDataProvider


@pytest.mark.asyncio
async def test_csv_data_provider_parses_file(tmp_path: Path):
    csv_path = tmp_path / "SOLUSDT_5.csv"
    rows = [
        {
            "timestamp": 1700000000000,
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "volume": 100,
        },
        {
            "timestamp": 1700000300000,
            "open": 10.5,
            "high": 11.5,
            "low": 10,
            "close": 11,
            "volume": 120,
        },
    ]
    header = "timestamp,open,high,low,close,volume\n"
    with csv_path.open("w", encoding="utf-8") as handle:
        handle.write(header)
        for row in rows:
            handle.write(
                ",".join(
                    str(row[k])
                    for k in ["timestamp", "open", "high", "low", "close", "volume"]
                )
            )
            handle.write("\n")

    provider = CsvDataProvider(csv_path=str(csv_path))
    df = await provider.fetch(
        "SOLUSDT", "5", start_date="2023-11-01", end_date="2023-12-01"
    )

    assert not df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.is_monotonic_increasing


@pytest.mark.asyncio
async def test_zoomex_data_provider_uses_client(monkeypatch):
    async def fake_get_klines(self, symbol: str, interval: str = "5", limit: int = 300):
        idx = pd.to_datetime([1700000000000, 1700000300000], unit="ms", utc=True)
        df = pd.DataFrame(
            {
                "open": [10.0, 10.5],
                "high": [11.0, 11.5],
                "low": [9.5, 10.0],
                "close": [10.2, 10.8],
                "volume": [100.0, 120.0],
            },
            index=idx,
        )
        df.index.name = "start"
        return df

    monkeypatch.setattr(zoomex_v3.ZoomexV3Client, "get_klines", fake_get_klines)
    provider = ZoomexDataProvider(use_testnet=True)
    df = await provider.fetch(
        "SOLUSDT", "5", start_date="2023-11-01", end_date="2023-12-01"
    )
    assert not df.empty
    assert "close" in df.columns
    assert df.index[0] < df.index[-1]
