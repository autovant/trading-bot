import logging
import sqlite3
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

import ccxt

from notifications import send_telegram_message_async
from src.strategies.dynamic_engine import DynamicStrategyEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradeEngine")


class TradingMode(Enum):
    LIVE = "LIVE"
    PAPER = "PAPER"


class TradeEngine:
    def __init__(
        self,
        mode: str = "PAPER",
        exchange_id: str = "binance",
        api_key: str = "",
        api_secret: str = "",
        db_path: str = "trades.db",
    ):
        self.mode = TradingMode(mode.upper())
        self.exchange_id = exchange_id
        self.db_path = db_path
        self.dynamic_engine = DynamicStrategyEngine(exchange_id=exchange_id)

        # Initialize Exchange
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            }
        )

        # Initialize Database
        self._init_db()

        logger.info(
            f"TradeEngine initialized in {self.mode.value} mode on {exchange_id}"
        )

    def _init_db(self):
        """Initialize SQLite database for trade tracking."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                symbol TEXT,
                side TEXT,
                amount REAL,
                price REAL,
                cost REAL,
                mode TEXT,
                order_id TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _log_trade(self, trade_data: Dict):
        """Log trade to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO trades (timestamp, symbol, side, amount, price, cost, mode, order_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                datetime.now().isoformat(),
                trade_data["symbol"],
                trade_data["side"],
                trade_data["amount"],
                trade_data["price"],
                trade_data["cost"],
                self.mode.value,
                trade_data.get("id", "paper_trade"),
            ),
        )
        conn.commit()
        conn.close()

    async def execute_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
        telegram_config: Optional[Dict[str, str]] = None,
    ):
        """
        Execute an order based on the current mode.

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            side: 'buy' or 'sell'
            amount: Quantity to trade
            price: Limit price (optional)
            order_type: 'market' or 'limit'
        """
        try:
            if self.mode == TradingMode.LIVE:
                return await self._execute_live(
                    symbol, side, amount, price, order_type, telegram_config
                )
            else:
                return await self._execute_paper(
                    symbol, side, amount, price, order_type, telegram_config
                )
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            raise

    async def _execute_live(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float],
        order_type: str,
        telegram_config: Optional[Dict[str, str]],
    ):
        """Execute order on real exchange."""
        if order_type == "market":
            order = self.exchange.create_market_order(symbol, side, amount)
        else:
            order = self.exchange.create_limit_order(symbol, side, amount, price)

        self._log_trade(
            {
                "symbol": symbol,
                "side": side,
                "amount": order["amount"],
                "price": order["average"] if order["average"] else order["price"],
                "cost": order["cost"],
                "id": order["id"],
            }
        )
        await self._notify_trade(
            side,
            amount,
            symbol,
            order["average"] if order["average"] else order["price"],
            telegram_config,
        )
        logger.info(f"LIVE Trade Executed: {side} {amount} {symbol}")
        return order

    async def _execute_paper(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float],
        order_type: str,
        telegram_config: Optional[Dict[str, str]],
    ):
        """Simulate order execution with slippage."""
        # Fetch current price for simulation
        ticker = self.exchange.fetch_ticker(symbol)
        current_price = ticker["last"]

        # Calculate Slippage (simulated 0.1%)
        slippage = 0.001
        execution_price = (
            current_price * (1 + slippage)
            if side == "buy"
            else current_price * (1 - slippage)
        )

        if order_type == "limit" and price:
            # Simple limit logic: only execute if price is better
            if (side == "buy" and execution_price > price) or (
                side == "sell" and execution_price < price
            ):
                logger.info("Paper limit order not filled")
                return None
            execution_price = (
                price  # Assume filled at limit price for simplicity in paper
            )

        cost = amount * execution_price

        trade_record = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": execution_price,
            "cost": cost,
            "id": f"paper_{int(datetime.now().timestamp())}",
        }

        self._log_trade(trade_record)
        await self._notify_trade(side, amount, symbol, execution_price, telegram_config)
        logger.info(
            f"PAPER Trade Executed: {side} {amount} {symbol} @ {execution_price}"
        )
        return trade_record

    async def _notify_trade(
        self,
        side: str,
        amount: float,
        symbol: str,
        price: float,
        telegram_config: Optional[Dict[str, str]],
    ):
        if not telegram_config:
            return
        token = telegram_config.get("bot_token")
        chat_id = telegram_config.get("chat_id")
        if not token or not chat_id:
            logger.warning("Missing Telegram credentials; skipping notification.")
            return
        message = f"Trade Alert: {side.upper()} {amount:.4f} {symbol} @ {price:.4f}"
        await send_telegram_message_async(token, chat_id, message)

    async def backtest_json_strategy(
        self,
        strategy_config: Dict[str, Any],
        symbol: str,
        start_date: str,
        end_date: str,
        optimization: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Convenience wrapper to run a JSON strategy through the dynamic engine from the TradeEngine facade.
        """
        return await self.dynamic_engine.run_backtest(
            strategy_config=strategy_config,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            optimization=optimization,
        )
