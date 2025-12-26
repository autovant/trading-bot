import logging
from pathlib import Path
from typing import Optional

import polars as pl

logger = logging.getLogger(__name__)


class PolarsDataStore:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

    def save_data(self, symbol: str, timeframe: str, df: pl.DataFrame):
        """Save DataFrame to Parquet for high performance."""
        filename = self._get_filename(symbol, timeframe)
        df.write_parquet(filename)
        logger.info(f"Saved {df.height} rows to {filename}")

    def load_data(self, symbol: str, timeframe: str) -> Optional[pl.DataFrame]:
        """Load DataFrame from Parquet."""
        filename = self._get_filename(symbol, timeframe)
        if not filename.exists():
            return None
        return pl.read_parquet(filename)

    def _get_filename(self, symbol: str, timeframe: str) -> Path:
        safe_symbol = symbol.replace("/", "_")
        return self.data_dir / f"{safe_symbol}_{timeframe}.parquet"

    def merge_data(self, old_df: pl.DataFrame, new_df: pl.DataFrame) -> pl.DataFrame:
        """Merge new data with existing data, removing duplicates."""
        # Concatenate and sort by timestamp
        combined = pl.concat([old_df, new_df])
        return combined.unique(subset=["timestamp"]).sort("timestamp")
