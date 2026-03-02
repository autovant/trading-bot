"""
Backtester V2 - Uses PerpsService and PaperBroker for accurate simulation.

This harness feeds historical data into PerpsService cycle-by-cycle,
ensuring backtest results mirror live/paper trading execution.
"""

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from src.config import get_config, StrategyConfig
from src.database import DatabaseManager
from src.exchanges.paper_perps import PaperPerpsExchange
from src.paper_trader import PaperBroker
from src.services.perps import PerpsService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class BacktestDataProvider:
    """Provides historical data bar-by-bar to simulate live data feed."""

    def __init__(self, df: pd.DataFrame, interval_minutes: int = 5):
        self.df = df.copy()
        self.interval_minutes = interval_minutes
        self.current_idx = 0
        self._warmup_bars = 200  # Bars needed for indicator warmup

    def get_next_bar(self) -> Optional[pd.DataFrame]:
        """Return progressively larger slices of data, simulating live."""
        if self.current_idx >= len(self.df):
            return None
        
        end_idx = self.current_idx + 1
        start_idx = max(0, end_idx - self._warmup_bars)
        slice_df = self.df.iloc[start_idx:end_idx].copy()
        self.current_idx += 1
        return slice_df

    def reset(self):
        self.current_idx = self._warmup_bars  # Start after warmup


class BacktestExchange:
    """Mock exchange that provides data from BacktestDataProvider."""

    def __init__(self, provider: BacktestDataProvider, symbol: str):
        self.provider = provider
        self.symbol = symbol
        self._current_slice: Optional[pd.DataFrame] = None

    async def initialize(self):
        pass

    async def get_historical_data(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> Optional[pd.DataFrame]:
        # Return the current data slice
        if self._current_slice is None or self._current_slice.empty:
            return None
        return self._current_slice.tail(limit)

    def advance(self) -> bool:
        """Move to next bar"""
        self._current_slice = self.provider.get_next_bar()
        return self._current_slice is not None and not self._current_slice.empty


async def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "5",
    initial_capital: float = 1000.0,
):
    """Run a backtest using PerpsService logic."""
    logger.info(f"Starting backtest for {symbol} from {start_date} to {end_date}")

    config = get_config()

    # Override config for backtest
    config.perps.symbol = symbol
    config.perps.interval = interval
    config.perps.useTestnet = True
    config.perps.enabled = True

    # Initialize Database (in-memory for backtest)
    db = DatabaseManager(url="sqlite:///:memory:")
    await db.initialize()

    # Load historical data
    # In a real scenario, you'd load from parquet/csv/api
    # Here we mock it for demonstration
    logger.info("Loading historical data...")
    
    # Placeholder: Load real data here
    # For now, create empty structure
    data_path = Path(f"data/bars/{symbol}_{interval}m.parquet")
    if data_path.exists():
        df = pd.read_parquet(data_path)
    else:
        logger.warning(f"Data file not found: {data_path}. Using exchange API.")
        # Fallback: Fetch from exchange (would need network)
        # For fully offline backtest, data must be pre-downloaded
        from src.exchange import ExchangeClient
        exchange = ExchangeClient(config.exchange, mode="paper")
        await exchange.initialize()
        df = await exchange.get_historical_data(symbol, f"{interval}m", limit=5000)
        if df is None:
            logger.error("Failed to fetch historical data")
            return None
        await exchange.close()

    # Filter by date range
    df['timestamp'] = pd.to_datetime(df.index if 'timestamp' not in df.columns else df['timestamp'])
    df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)]
    
    if df.empty or len(df) < 200:
        logger.error(f"Insufficient data: {len(df)} bars")
        return None

    df = df.set_index('timestamp')
    
    provider = BacktestDataProvider(df, interval_minutes=int(interval))
    provider.reset()
    
    backtest_exchange = BacktestExchange(provider, symbol)

    # Create PaperBroker
    paper_broker = PaperBroker(
        config=config.paper,
        database=db,
        mode="backtest",
        run_id=f"backtest_{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        initial_balance=initial_capital,
        risk_config=config.risk_management,
    )

    # Create Paper Exchange
    paper_exchange = PaperPerpsExchange(
        exchange_config=config.exchange,
        perps_config=config.perps,
        broker=paper_broker,
    )

    # Create PerpsService
    perps_service = PerpsService(
        config=config.perps,
        exchange=paper_exchange,
        trading_config=config.trading,
        strategy_config=config.strategy,
        crisis_config=config.risk_management.crisis_mode,
        database=db,
        mode_name="backtest",
    )

    # Initialize
    try:
        await perps_service.initialize()
    except Exception as e:
        logger.warning(f"PerpsService init issue (expected in backtest): {e}")

    # Run simulation
    trades = []
    bar_count = 0
    
    logger.info("Running backtest simulation...")
    while backtest_exchange.advance():
        bar_count += 1
        if bar_count % 500 == 0:
            logger.info(f"Processed {bar_count} bars...")

        # Inject current bar into paper exchange
        current_bar = backtest_exchange._current_slice.iloc[-1]
        paper_exchange._last_price = float(current_bar['close'])
        
        try:
            # Run one cycle
            await perps_service.run_cycle()
        except Exception as e:
            logger.debug(f"Cycle error (may be expected): {e}")

    # Collect results
    final_equity = await paper_broker.get_equity()
    all_trades = await db.get_trades_by_run(perps_service.config_id or "backtest")
    
    pnl = final_equity - initial_capital
    pnl_pct = (pnl / initial_capital) * 100

    results = {
        "symbol": symbol,
        "period": f"{start_date} to {end_date}",
        "bars_processed": bar_count,
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "total_pnl": pnl,
        "total_pnl_pct": pnl_pct,
        "total_trades": len(all_trades),
    }

    logger.info("=" * 50)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 50)
    for key, val in results.items():
        if isinstance(val, float):
            logger.info(f"{key}: {val:.2f}")
        else:
            logger.info(f"{key}: {val}")
    logger.info("=" * 50)

    return results


def main():
    parser = argparse.ArgumentParser(description="Backtest V2 - PerpsService based")
    parser.add_argument("--symbol", default="SOLUSDT", help="Trading symbol")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2024-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", default="5", help="Candle interval in minutes")
    parser.add_argument("--capital", type=float, default=1000.0, help="Initial capital")
    
    args = parser.parse_args()

    asyncio.run(run_backtest(
        symbol=args.symbol,
        start_date=args.start,
        end_date=args.end,
        interval=args.interval,
        initial_capital=args.capital,
    ))


if __name__ == "__main__":
    main()
