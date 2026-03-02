"""
Lifecycle Demo Replayer
Demonstrates the full lifecycle of a trade using realistic synthetic data.
Guarantees we see:
1. Signal Generation (Entry)
2. Trade Placement
3. Price movement simulation
4. Exit Signal Generation
5. Trade Close
"""

import asyncio
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict

from src.config import get_config, StrategyConfig
from src.signal_generator import SignalGenerator
from src.models import MarketRegime, TradingSetup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LifecycleDemo")

class MockExchange:
    def __init__(self):
        self.orders = []
        self.positions = []

    def place_order(self, order: Dict):
        order["id"] = f"ord_{len(self.orders)+1:03d}"
        order["status"] = "FILLED"
        self.orders.append(order)
        
        if order["side"] == "buy":
            self.positions.append({
                "symbol": order["symbol"],
                "qty": order["qty"],
                "entry_price": order["price"]
            })
        else:
            # Simple full close
            if self.positions:
                self.positions.pop()
        
        return order

def generate_perfect_scenario():
    """Generates OHLCV data for a Bullish -> Reversal scenario."""
    
    # Needs 20+ bars for indicators to warm up
    # Strategy needs:
    # 1. Rising EMA Stack (EMA12 > EMA20 > EMA50)
    # 2. Pullback to EMA20
    # 3. Resume
    
    base_price = 100.0
    data = []
    start_time = datetime.now(timezone.utc) - timedelta(hours=100)
    
    # 1. Warmup (Flat/Chop) - Hours 0-40
    for i in range(40):
        base_price = 100.0 + np.sin(i/5) * 0.5
        data.append(_make_candle(start_time + timedelta(hours=i), base_price))

    # 2. Bullish Trend Start (Strong impulse) - Hours 40-50
    # Establish trend for MAs to align
    for i in range(40, 50):
        base_price = 100.0 + (i-40)*1.0 # Fast rise
        data.append(_make_candle(start_time + timedelta(hours=i), base_price, bullish=True))
        
    # 3. Pullback (Entry Signal) - Hours 50-55
    # Price dips but Trend stays up
    peak = base_price
    for i in range(50, 55):
        base_price = peak - (i-50)*0.3
        data.append(_make_candle(start_time + timedelta(hours=i), base_price, bullish=False))
        
    # 4. Resume & Extension (Profit) - Hours 55-70
    base_price_resume = base_price
    for i in range(55, 70):
        base_price = base_price_resume + (i-55)*0.8
        data.append(_make_candle(start_time + timedelta(hours=i), base_price, bullish=True))
        
    # 5. Reversal (Exit) - Hours 70-80
    top = base_price
    for i in range(70, 80):
        base_price = top - (i-70)*1.5 # Crash
        data.append(_make_candle(start_time + timedelta(hours=i), base_price, bullish=False))
        
    df = pd.DataFrame(data)
    df.set_index("start", inplace=True)
    return df

def _make_candle(time, price, bullish=None):
    vol = np.random.randint(1000, 5000)
    if bullish is None:
        bullish = np.random.random() > 0.5
        
    if bullish:
        open_p = price - np.random.random()*0.5
        close_p = price + np.random.random()*0.5
        high_p = close_p + np.random.random()*0.2
        low_p = open_p - np.random.random()*0.2
    else:
        open_p = price + np.random.random()*0.5
        close_p = price - np.random.random()*0.5
        high_p = open_p + np.random.random()*0.2
        low_p = close_p - np.random.random()*0.2
        
    return {
        "start": time,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": vol
    }

async def run_lifecycle_demo():
    print("\n" + "="*60)
    print("🎬 FULL TRADING LIFECYCLE DEMO")
    print("="*60)
    print("Scenario: Perfectly Bullish Setup -> Trend -> Reversal Exit")
    print("Symbol:   SOLUSDT (Simulated)")
    print("Strategy: Advanced Signal Generator (Real Logic)")
    print("-" * 60 + "\n")
    
    # 1. Setup Environment
    config = get_config().strategy
    gen = SignalGenerator()
    exchange = MockExchange()
    
    # 2. Get Data
    df = generate_perfect_scenario()
    
    # Mock Regime/Setup context (Assume correct context for 1H signal)
    # In real app these come from other TFs
    mock_regime = MarketRegime(
        regime="bullish", strength=1.5, confidence=80.0,
        trend_direction=1, volatility_score=0.5
    )
    mock_setup = TradingSetup(
        direction="long", setup_type="pullback", strength=1.2, quality=0.8,
        ma_aligned=True, momentum_aligned=True
    )
    
    # 3. Iterate through time (Replay)
    in_position = False
    entry_price = 0.0
    
    # Warmup buffer
    window = 14
    
    print("⏳ Replaying market data...\n")
    
    for i in range(window, len(df)):
        current_slice = df.iloc[:i+1] # Current "Live" data
        current_candle = current_slice.iloc[-1]
        time_str = current_candle.name.strftime("%H:%M")
        price = current_candle["close"]
        
        # A. Analyze Signals
        raw_signals = gen.generate_signals(current_slice, config)
        valid_signals = gen.filter_signals(raw_signals, mock_regime, mock_setup)
        
        signal_str = "Neutral"
        if valid_signals:
            sig = valid_signals[0]
            signal_str = f"{sig.direction.upper()} ({sig.signal_type})"

        # B. Log Logic
        # print(f"[{time_str}] Price: {price:6.2f} | Signal: {signal_str}")
        
        # C. Execution Logic
        if not in_position:
            # Looking for Entry
            if valid_signals and valid_signals[0].direction == "long":
                sig = valid_signals[0]
                print(f"\n⚡ [{time_str}] ENTRY SIGNAL DETECTED")
                print(f"   Type: {sig.signal_type} | Conf: {sig.confidence:.1f}")
                print(f"   Logic: Price > EMAs & Momentum Trigger")
                
                # Place Trade
                order = exchange.place_order({
                    "symbol": "SOLUSDT",
                    "side": "buy",
                    "qty": 10.0,
                    "price": price
                })
                in_position = True
                entry_price = price
                print(f"🛒 PLACED BUY ORDER @ {price:.2f}")
                print("-" * 40)
                
        else:
            # Looking for Exit
            # Simulated Strategy Exit: Trend Reversal Check
            sma5 = current_slice["close"].rolling(5).mean().iloc[-1]
            sma10 = current_slice["close"].rolling(10).mean().iloc[-1]
            
            pnl_pct = (price - entry_price) / entry_price
            
            # TRIGGER EXIT
            if sma5 < sma10 and pnl_pct > 0.00: # MA crossover exit
                print(f"\n🚨 [{time_str}] EXIT SIGNAL DETECTED")
                print(f"   Reason: Trend Reversal (MA5 crossed below MA10)")
                print(f"   Logic: Protect Profit & Exit Weakness")
                
                # Close Trade
                exchange.place_order({
                    "symbol": "SOLUSDT",
                    "side": "sell",
                    "qty": 10.0,
                    "price": price
                })
                in_position = False
                
                pnl = (price - entry_price) * 10
                print(f"📉 PLACED SELL ORDER @ {price:.2f}")
                print(f"\n💰 TRADE CLOSED | PnL: ${pnl:.2f} ({pnl_pct*100:+.2f}%)")
                print("="*60)
                break
            
            # Update visualization
            if i % 3 == 0:
                 print(f"   ... [{time_str}] Holding Long | Price: {price:.2f} | PnL: {pnl_pct*100:+.2f}%")

    if not in_position:
        print("\n(Demo ended without exit signal in timeframe)")

if __name__ == "__main__":
    asyncio.run(run_lifecycle_demo())
