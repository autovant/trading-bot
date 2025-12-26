import asyncio
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())


async def verify():
    print("Verifying imports...")
    try:
        from src.application.strategy_manager import StrategyManager
        from src.infrastructure.datastore.polars_store import PolarsDataStore
        from src.infrastructure.exchange.ccxt_adapter import CCXTAdapter
        from src.infrastructure.persistence.sqlite_repo import SQLiteRepository
        from src.strategies.stat_arb import StatisticalArbitrageStrategy

        print("Imports successful.")

        print("Instantiating components...")
        PolarsDataStore()
        SQLiteRepository()

        # Mock exchange
        exchange = CCXTAdapter("bybit", "key", "secret", testnet=True)

        manager = StrategyManager(exchange, exchange)
        strategy = StatisticalArbitrageStrategy(("BTC/USDT", "ETH/USDT"))

        manager.register_strategy("stat_arb", strategy)

        print("Instantiation successful.")

    except Exception as e:
        print(f"Verification failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(verify())
