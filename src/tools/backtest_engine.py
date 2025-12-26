import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

import aiohttp
import pandas as pd

from src.config import load_config
from src.exchanges.zoomex_v3 import ZoomexV3Client
from tools.backtest_perps import PerpsBacktest

logger = logging.getLogger("BacktestEngine")


class BacktestEngine:
    def __init__(self):
        self.logs = []

    async def fetch_historical_data(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch full historical data from Zoomex."""
        # Reuse logic from CLI tool, but localized here
        interval_map = {
            "1": 1,
            "5": 5,
            "15": 15,
            "30": 30,
            "60": 60,
            "240": 240,
            "D": 1440,
        }
        interval_minutes = interval_map.get(interval, 1)

        async with aiohttp.ClientSession() as session:
            client = ZoomexV3Client(session, base_url="https://openapi.zoomex.com")

            all_klines = []
            current_end = end_date

            while current_end > start_date:
                end_ts = int(current_end.timestamp() * 1000)
                try:
                    chunk = await client.get_klines(
                        symbol=symbol, interval=interval, limit=limit, end=end_ts
                    )
                except Exception as e:
                    logger.error(f"Error fetching data: {e}")
                    break

                if chunk.empty:
                    break

                all_klines.append(chunk)
                oldest_time = chunk.index[0]

                if oldest_time >= current_end:
                    current_end -= timedelta(minutes=interval_minutes * limit)
                else:
                    current_end = oldest_time

                # Rate limit protection
                await asyncio.sleep(0.1)

        if not all_klines:
            return pd.DataFrame()

        full_df = pd.concat(all_klines)
        full_df = full_df.sort_index()
        full_df = full_df[~full_df.index.duplicated(keep="first")]
        return full_df[(full_df.index >= start_date) & (full_df.index <= end_date)]

    async def run(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        risk_pct: float = 0.02,
        leverage: int = 5,
        use_multi_tf: bool = False,
    ) -> Dict[str, Any]:
        ltf_df = await self.fetch_historical_data(
            symbol, interval, start_date, end_date
        )
        if ltf_df.empty:
            return {"error": "No data fetched"}

        config = load_config()
        config.perps.useMultiTfAtrStrategy = use_multi_tf
        config.perps.symbol = symbol
        config.perps.interval = interval
        config.perps.enabled = True
        config.perps.riskPct = risk_pct
        config.perps.leverage = leverage

        htf_df = None
        if use_multi_tf:
            htf_df = await self.fetch_historical_data(
                symbol, config.perps.htfInterval, start_date, end_date
            )

        backtest = PerpsBacktest(
            config.perps,
            initial_balance=initial_capital,
            use_multi_tf=use_multi_tf,
        )
        metrics = backtest.run_backtest(ltf_df, htf_df)

        return {
            "metrics": metrics,
            "equity_curve": backtest.equity_curve,
            "trades": backtest.trades,
            "symbol": symbol,
            "interval": interval,
            "strategy": "Multi-TF" if use_multi_tf else "Simple",
        }
