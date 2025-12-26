from datetime import datetime
from typing import List

import aiosqlite

from src.domain.entities import Side, Trade
from src.domain.interfaces import IRepository


class SQLiteRepository(IRepository):
    def __init__(self, db_path: str = "trading_bot.db"):
        self.db_path = db_path

    async def initialize(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    order_id TEXT,
                    symbol TEXT,
                    side TEXT,
                    quantity REAL,
                    price REAL,
                    commission REAL,
                    timestamp TEXT
                )
            """)
            await db.commit()

    async def save_trade(self, trade: Trade):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO trades (id, order_id, symbol, side, quantity, price, commission, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    trade.id,
                    trade.order_id,
                    trade.symbol,
                    trade.side.value,
                    trade.quantity,
                    trade.price,
                    trade.commission,
                    trade.timestamp.isoformat(),
                ),
            )
            await db.commit()

    async def get_trades(self, symbol: str) -> List[Trade]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trades WHERE symbol = ?", (symbol,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    Trade(
                        id=row["id"],
                        order_id=row["order_id"],
                        symbol=row["symbol"],
                        side=Side(row["side"]),
                        quantity=row["quantity"],
                        price=row["price"],
                        commission=row["commission"],
                        timestamp=datetime.fromisoformat(row["timestamp"]),
                    )
                    for row in rows
                ]
