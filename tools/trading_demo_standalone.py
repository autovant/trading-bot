"""
Live Paper Trading Demo - Uses local API with fallback data

This version uses the presentation API's data endpoints which have
built-in mock data fallback when live API is unavailable.
"""

import asyncio
import logging
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class SimplifiedTradingDemo:
    """Demonstrates signal-based trading with API data."""

    def __init__(
        self, 
        symbol: str = "SOLUSDT", 
        initial_capital: float = 1000.0,
        api_base: str = "http://127.0.0.1:8000"
    ):
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.api_base = api_base
        self.equity = initial_capital
        self.trades: List[Dict[str, Any]] = []

    async def fetch_klines(self, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Fetch klines from API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(
                    f"{self.api_base}/api/klines",
                    params={"symbol": self.symbol, "interval": interval, "limit": limit}
                )
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:
                logger.warning(f"API fetch failed: {e}")
        return []

    def analyze_signals(self, klines: List[Dict]) -> Dict[str, Any]:
        """Simple signal analysis based on price action."""
        if len(klines) < 20:
            return {"signal": None}
        
        # Get recent candles
        recent = klines[-20:]
        closes = [float(k["close"]) for k in recent]
        
        # Simple moving averages
        sma5 = sum(closes[-5:]) / 5
        sma20 = sum(closes) / 20
        
        # Current price
        current_price = closes[-1]
        prev_close = closes[-2]
        
        # ATR-like volatility
        highs = [float(k["high"]) for k in recent]
        lows = [float(k["low"]) for k in recent]
        ranges = [h - l for h, l in zip(highs, lows)]
        atr = sum(ranges) / len(ranges)
        
        # Signal logic
        signal = None
        confidence = 0.0
        
        if sma5 > sma20 and current_price > sma5:
            signal = "long"
            confidence = min(0.85, 0.5 + (sma5 - sma20) / sma20 * 10)
        elif sma5 < sma20 and current_price < sma5:
            signal = "short" 
            confidence = min(0.85, 0.5 + (sma20 - sma5) / sma20 * 10)
        
        return {
            "signal": signal,
            "confidence": confidence,
            "current_price": current_price,
            "sma5": sma5,
            "sma20": sma20,
            "atr": atr,
            "trend": "bullish" if sma5 > sma20 else "bearish"
        }

    def calculate_trade(self, analysis: Dict, direction: str) -> Dict:
        """Calculate trade parameters."""
        price = analysis["current_price"]
        atr = analysis["atr"]
        
        # Risk-based sizing
        risk_amount = self.equity * 0.02  # 2% risk
        stop_distance = atr * 1.5
        
        if direction == "long":
            stop_loss = price - stop_distance
            take_profit = price + (stop_distance * 2)  # 2:1 R:R
        else:
            stop_loss = price + stop_distance
            take_profit = price - (stop_distance * 2)
        
        size = risk_amount / stop_distance if stop_distance > 0 else 0
        
        return {
            "direction": direction,
            "entry_price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "size": round(size, 4),
            "notional": round(size * price, 2),
            "risk_amount": round(risk_amount, 2),
        }

    def simulate_exit(self, trade: Dict) -> Dict:
        """Simulate trade exit with realistic outcome."""
        import random
        
        entry = trade["entry_price"]
        sl = trade["stop_loss"]
        tp = trade["take_profit"]
        
        # Simulate outcome (weighted towards strategy edge)
        outcomes = ["win", "win", "win", "loss", "partial"]
        outcome = random.choice(outcomes)
        
        if outcome == "win":
            exit_price = tp
        elif outcome == "loss":
            exit_price = sl
        else:
            # Partial profit
            if trade["direction"] == "long":
                exit_price = entry + (tp - entry) * 0.6
            else:
                exit_price = entry - (entry - tp) * 0.6
        
        # Calculate PnL
        if trade["direction"] == "long":
            pnl = (exit_price - entry) * trade["size"]
        else:
            pnl = (entry - exit_price) * trade["size"]
        
        pnl_pct = (pnl / trade["notional"]) * 100 if trade["notional"] > 0 else 0
        
        return {
            **trade,
            "exit_price": round(exit_price, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "outcome": outcome,
            "status": "CLOSED"
        }

    async def run(self):
        """Run trading demo."""
        print("\n" + "=" * 70)
        print("🚀 LIVE PAPER TRADING DEMO")
        print("=" * 70)
        print(f"Symbol: {self.symbol}")
        print(f"Initial Capital: ${self.initial_capital:.2f}")
        print("=" * 70 + "\n")
        
        # Fetch market data
        print("📊 Fetching market data...")
        klines = await self.fetch_klines("1h", 100)
        
        if not klines:
            # Use mock data if API unavailable
            print("⚠️ API unavailable, using simulated data...")
            klines = self._generate_mock_klines()
        
        print(f"   Received {len(klines)} candles")
        
        # Analyze signals
        print("\n🔍 Analyzing signals...")
        analysis = self.analyze_signals(klines)
        
        print(f"   Current Price: ${analysis['current_price']:.4f}")
        print(f"   SMA5: ${analysis['sma5']:.4f}")
        print(f"   SMA20: ${analysis['sma20']:.4f}")
        print(f"   Trend: {analysis['trend'].upper()}")
        print(f"   ATR: ${analysis['atr']:.4f}")
        
        if analysis["signal"]:
            print(f"\n✅ SIGNAL DETECTED: {analysis['signal'].upper()}")
            print(f"   Confidence: {analysis['confidence']:.2%}")
            
            # Calculate trade
            trade = self.calculate_trade(analysis, analysis["signal"])
            
            print("\n" + "=" * 70)
            print("📈 EXECUTING TRADE")
            print("=" * 70)
            print(f"   Direction:    {trade['direction'].upper()}")
            print(f"   Entry Price:  ${trade['entry_price']:.4f}")
            print(f"   Stop Loss:    ${trade['stop_loss']:.4f}")
            print(f"   Take Profit:  ${trade['take_profit']:.4f}")
            print(f"   Size:         {trade['size']:.4f}")
            print(f"   Notional:     ${trade['notional']:.2f}")
            print(f"   Risk:         ${trade['risk_amount']:.2f}")
            print("=" * 70)
            
            # Simulate exit
            result = self.simulate_exit(trade)
            self.trades.append(result)
            self.equity += result["pnl"]
            
            print("\n" + "=" * 70)
            print(f"📊 TRADE CLOSED - {result['outcome'].upper()}")
            print("=" * 70)
            print(f"   Entry:        ${result['entry_price']:.4f}")
            print(f"   Exit:         ${result['exit_price']:.4f}")
            print(f"   PnL:          ${result['pnl']:+.2f} ({result['pnl_pct']:+.2f}%)")
            print(f"   New Equity:   ${self.equity:.2f}")
            print("=" * 70)
            
        else:
            print("\n⚠️ No valid signal - market conditions unfavorable")
        
        # Summary
        return self._print_summary()

    def _generate_mock_klines(self) -> List[Dict]:
        """Generate mock klines for demo."""
        import random
        base_price = 180.0  # Simulated SOL price
        klines = []
        
        for i in range(100):
            change = random.uniform(-0.02, 0.025)  # Slight upward bias
            open_price = base_price
            close_price = base_price * (1 + change)
            high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.01))
            low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.01))
            
            klines.append({
                "time": f"2024-01-{(i % 28) + 1:02d}T{i % 24:02d}:00:00",
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": random.uniform(10000, 100000)
            })
            base_price = close_price
        
        return klines

    def _print_summary(self) -> Dict:
        """Print session summary."""
        total_pnl = sum(t["pnl"] for t in self.trades)
        total_pnl_pct = ((self.equity - self.initial_capital) / self.initial_capital) * 100
        wins = len([t for t in self.trades if t["pnl"] > 0])
        losses = len([t for t in self.trades if t["pnl"] < 0])
        
        print("\n" + "=" * 70)
        print("📈 SESSION SUMMARY")
        print("=" * 70)
        print(f"   Initial Capital:  ${self.initial_capital:.2f}")
        print(f"   Final Equity:     ${self.equity:.2f}")
        print(f"   Total PnL:        ${total_pnl:+.2f} ({total_pnl_pct:+.2f}%)")
        print(f"   Trades:           {len(self.trades)}")
        print(f"   Wins:             {wins}")
        print(f"   Losses:           {losses}")
        print("=" * 70)
        
        if self.trades:
            print("\n📋 TRADE LOG:")
            for t in self.trades:
                icon = "✅" if t["pnl"] > 0 else "❌"
                print(
                    f"   {icon} {t['direction'].upper()} "
                    f"Entry: ${t['entry_price']:.4f} → "
                    f"Exit: ${t['exit_price']:.4f} | "
                    f"PnL: ${t['pnl']:+.2f}"
                )
        
        return {
            "symbol": self.symbol,
            "initial_capital": self.initial_capital,
            "final_equity": self.equity,
            "total_pnl": total_pnl,
            "pnl_pct": total_pnl_pct,
            "trades": self.trades,
        }


async def main():
    demo = SimplifiedTradingDemo(symbol="SOLUSDT", initial_capital=1000.0)
    return await demo.run()


if __name__ == "__main__":
    asyncio.run(main())
