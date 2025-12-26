import asyncio
import logging

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backtest.backtester import run_backtest
from core.data_feed import MarketStream
from core.engine import TradeEngine
from strategies.alpha_logic import VolatilityBreakoutStrategy

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

app = FastAPI(title="Trading Bot API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Components
engine = TradeEngine(mode="PAPER")
feed = MarketStream(symbols=["BTC/USDT"])
strategy = VolatilityBreakoutStrategy()

# Global State (simplified for demo)
state = {"current_price": 0.0, "open_positions": [], "account_balance": 10000.0}


@app.on_event("startup")
async def startup_event():
    await feed.start()
    asyncio.create_task(market_data_consumer())


@app.on_event("shutdown")
async def shutdown_event():
    await feed.stop()


async def market_data_consumer():
    """Consume market data and update state."""
    while True:
        update = await feed.get_latest()
        if update["type"] == "candle":
            price = update["data"]["close"]
            state["current_price"] = price

            # Run Strategy
            signal = strategy.on_candle(update["data"])
            if signal:
                logger.info(f"Signal: {signal}")
                await engine.execute_order(
                    symbol=update["symbol"],
                    side=signal["action"],
                    amount=signal["amount"],
                )
                # Update positions (mock)
                if signal["action"] == "buy":
                    state["open_positions"].append(signal)
                elif signal["action"] == "sell":
                    state["open_positions"] = []  # Clear for simplicity


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Push updates every 100ms-1000ms
            payload = {
                "current_price": state["current_price"],
                "open_positions": state["open_positions"],
                "account_balance": state[
                    "account_balance"
                ],  # In real app, fetch from engine/db
            }
            await websocket.send_json(payload)
            await asyncio.sleep(0.5)  # 500ms
    except WebSocketDisconnect:
        logger.info("Client disconnected")


@app.get("/backtest")
async def trigger_backtest():
    """Run backtest and return results."""
    return await run_backtest(strategy)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
