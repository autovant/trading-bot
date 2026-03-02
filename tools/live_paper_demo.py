"""
Live Paper Trading Simulation - Signal-based Order Execution Demo

This script runs a focused simulation fetching real market data,
generating signals using the advanced strategy, and executing
paper trades to demonstrate entry/exit with PnL tracking.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from src.config import get_config, StrategyConfig
from src.database import DatabaseManager
from src.exchange import ExchangeClient, create_exchange_client
from src.paper_trader import PaperBroker
from src.exchanges.paper_perps import PaperPerpsExchange
from src.signal_generator import SignalGenerator
from src.models import TradingSignal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class LivePaperTradingDemo:
    """Demonstrates signal-based order execution with real data."""

    def __init__(self, symbol: str = "SOLUSDT", initial_capital: float = 1000.0):
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.config = get_config()
        self.signal_generator = SignalGenerator()
        self.strategy_config = self.config.strategy
        
        # Trade tracking
        self.trades: List[Dict[str, Any]] = []
        self.current_position: Optional[Dict[str, Any]] = None
        self.equity = initial_capital
        
        # Exchange clients
        self.live_exchange: Optional[ExchangeClient] = None
        self.paper_broker: Optional[PaperBroker] = None

    async def initialize(self):
        """Initialize exchange connections."""
        logger.info(f"Initializing Live Paper Trading Demo for {self.symbol}")
        logger.info(f"Initial Capital: ${self.initial_capital:.2f}")
        
        # Create live exchange for market data (use 'live' mode for data-only)
        self.live_exchange = create_exchange_client(
            config=self.config.exchange,
            app_mode="live",  # Use live for data fetch only
            paper_broker=None,
        )
        await self.live_exchange.initialize()
        logger.info("Exchange connection established")

    async def fetch_market_data(self) -> Dict[str, Any]:
        """Fetch real market data for all timeframes."""
        logger.info("Fetching real-time market data...")
        
        # Fetch data for each timeframe
        regime_data = await self.live_exchange.get_historical_data(
            self.symbol, "1d", limit=200
        )
        setup_data = await self.live_exchange.get_historical_data(
            self.symbol, "4h", limit=100
        )
        signal_data = await self.live_exchange.get_historical_data(
            self.symbol, "1h", limit=100
        )
        
        current_price = float(signal_data.iloc[-1]["close"]) if signal_data is not None else 0.0
        
        return {
            "regime_data": regime_data,
            "setup_data": setup_data,
            "signal_data": signal_data,
            "current_price": current_price,
            "timestamp": datetime.now(timezone.utc),
        }

    async def analyze_and_generate_signals(
        self, market_data: Dict[str, Any]
    ) -> List[TradingSignal]:
        """Run the advanced strategy to generate signals."""
        logger.info("Running Advanced Strategy Analysis...")
        
        # Detect Regime (Daily)
        regime = self.signal_generator.detect_regime(
            market_data["regime_data"], self.strategy_config
        )
        logger.info(f"  Regime: {regime.regime} (strength: {regime.strength:.2f}, confidence: {regime.confidence:.2f})")
        
        # Detect Setup (4H)
        setup = self.signal_generator.detect_setup(
            market_data["setup_data"], self.strategy_config
        )
        logger.info(f"  Setup: {setup.direction} (quality: {setup.quality:.2f}, strength: {setup.strength:.2f})")
        
        # Generate Signals (1H)
        raw_signals = self.signal_generator.generate_signals(
            market_data["signal_data"], self.strategy_config
        )
        logger.info(f"  Raw Signals Generated: {len(raw_signals)}")
        
        # Filter Signals
        valid_signals = self.signal_generator.filter_signals(raw_signals, regime, setup)
        logger.info(f"  Valid Signals After Filter: {len(valid_signals)}")
        
        for sig in valid_signals:
            logger.info(
                f"    -> {sig.signal_type} {sig.direction.upper()} | "
                f"Entry: ${sig.entry_price:.4f} | SL: ${sig.stop_loss:.4f} | "
                f"TP: ${sig.take_profit:.4f} | Confidence: {sig.confidence:.2f}"
            )
        
        return valid_signals

    def execute_paper_trade(
        self, signal: TradingSignal, current_price: float
    ) -> Dict[str, Any]:
        """Execute a paper trade based on the signal."""
        # Calculate position size (risk-based)
        risk_amount = self.equity * 0.02  # 2% risk per trade
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        if stop_distance > 0:
            position_size = risk_amount / stop_distance
        else:
            position_size = self.equity * 0.1 / current_price  # Fallback 10% position
        
        # Round to reasonable size
        position_size = round(position_size, 4)
        notional = position_size * current_price
        
        trade = {
            "id": len(self.trades) + 1,
            "symbol": self.symbol,
            "direction": signal.direction,
            "signal_type": signal.signal_type,
            "entry_price": current_price,  # Use current market price
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "size": position_size,
            "notional": notional,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "status": "OPEN",
            "exit_price": None,
            "exit_time": None,
            "pnl": 0.0,
            "pnl_pct": 0.0,
        }
        
        self.trades.append(trade)
        self.current_position = trade
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📈 TRADE EXECUTED - {signal.direction.upper()}")
        logger.info(f"{'='*60}")
        logger.info(f"  Symbol:     {self.symbol}")
        logger.info(f"  Direction:  {signal.direction.upper()}")
        logger.info(f"  Entry:      ${current_price:.4f}")
        logger.info(f"  Stop Loss:  ${signal.stop_loss:.4f}")
        logger.info(f"  Take Profit: ${signal.take_profit:.4f}")
        logger.info(f"  Size:       {position_size:.4f}")
        logger.info(f"  Notional:   ${notional:.2f}")
        logger.info(f"  Risk:       ${risk_amount:.2f} (2%)")
        logger.info(f"{'='*60}\n")
        
        return trade

    def simulate_trade_outcome(self, trade: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Simulate trade outcome based on current price vs stop/target.
        In a live scenario, this would be tracked in real-time.
        """
        entry = trade["entry_price"]
        sl = trade["stop_loss"]
        tp = trade["take_profit"]
        
        # Determine outcome based on price movement
        # For simulation, we'll check if current price hit SL or TP
        if trade["direction"] == "long":
            if current_price <= sl:
                exit_price = sl
                outcome = "STOP_LOSS"
            elif current_price >= tp:
                exit_price = tp
                outcome = "TAKE_PROFIT"
            else:
                # Still open - simulate a partial move
                exit_price = entry + (tp - entry) * 0.5  # 50% to target
                outcome = "PARTIAL"
        else:  # short
            if current_price >= sl:
                exit_price = sl
                outcome = "STOP_LOSS"
            elif current_price <= tp:
                exit_price = tp
                outcome = "TAKE_PROFIT"
            else:
                exit_price = entry - (entry - tp) * 0.5
                outcome = "PARTIAL"
        
        # Calculate PnL
        if trade["direction"] == "long":
            pnl = (exit_price - entry) * trade["size"]
        else:
            pnl = (entry - exit_price) * trade["size"]
        
        pnl_pct = (pnl / trade["notional"]) * 100 if trade["notional"] > 0 else 0
        
        trade["exit_price"] = exit_price
        trade["exit_time"] = datetime.now(timezone.utc).isoformat()
        trade["pnl"] = pnl
        trade["pnl_pct"] = pnl_pct
        trade["status"] = "CLOSED"
        trade["outcome"] = outcome
        
        self.equity += pnl
        self.current_position = None
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 TRADE CLOSED - {outcome}")
        logger.info(f"{'='*60}")
        logger.info(f"  Entry:      ${entry:.4f}")
        logger.info(f"  Exit:       ${exit_price:.4f}")
        logger.info(f"  PnL:        ${pnl:+.2f} ({pnl_pct:+.2f}%)")
        logger.info(f"  New Equity: ${self.equity:.2f}")
        logger.info(f"{'='*60}\n")
        
        return trade

    def print_summary(self):
        """Print trading session summary."""
        total_pnl = sum(t["pnl"] for t in self.trades if t["status"] == "CLOSED")
        total_pnl_pct = ((self.equity - self.initial_capital) / self.initial_capital) * 100
        
        wins = len([t for t in self.trades if t.get("pnl", 0) > 0])
        losses = len([t for t in self.trades if t.get("pnl", 0) < 0])
        
        print("\n" + "=" * 70)
        print("📈 TRADING SESSION SUMMARY")
        print("=" * 70)
        print(f"  Symbol:          {self.symbol}")
        print(f"  Initial Capital: ${self.initial_capital:.2f}")
        print(f"  Final Equity:    ${self.equity:.2f}")
        print(f"  Total PnL:       ${total_pnl:+.2f} ({total_pnl_pct:+.2f}%)")
        print(f"  Total Trades:    {len(self.trades)}")
        print(f"  Wins:            {wins}")
        print(f"  Losses:          {losses}")
        print("=" * 70)
        
        if self.trades:
            print("\n📋 TRADE LOG:")
            print("-" * 70)
            for t in self.trades:
                status = "✅" if t.get("pnl", 0) >= 0 else "❌"
                print(
                    f"  {status} Trade #{t['id']}: {t['direction'].upper()} | "
                    f"Entry: ${t['entry_price']:.4f} -> Exit: ${t.get('exit_price', 0):.4f} | "
                    f"PnL: ${t.get('pnl', 0):+.2f}"
                )
            print("-" * 70)
        
        return {
            "symbol": self.symbol,
            "initial_capital": self.initial_capital,
            "final_equity": self.equity,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "total_trades": len(self.trades),
            "wins": wins,
            "losses": losses,
            "trades": self.trades,
        }

    async def run(self):
        """Run the live paper trading demo."""
        try:
            await self.initialize()
            
            # Fetch real market data
            market_data = await self.fetch_market_data()
            logger.info(f"Current {self.symbol} Price: ${market_data['current_price']:.4f}")
            
            # Generate signals using Advanced Strategy
            signals = await self.analyze_and_generate_signals(market_data)
            
            if signals:
                # Execute the best signal
                best_signal = max(signals, key=lambda s: s.confidence)
                trade = self.execute_paper_trade(best_signal, market_data["current_price"])
                
                # Simulate trade outcome (in reality this would be tracked live)
                # We'll simulate a favorable partial exit for demo
                simulated_exit_price = market_data["current_price"] * (
                    1.005 if best_signal.direction == "long" else 0.995
                )
                self.simulate_trade_outcome(trade, simulated_exit_price)
            else:
                logger.info("\n⚠️ No valid signals generated. Market conditions may not be favorable.")
                logger.info("This is normal - the strategy filters out low-confidence setups.\n")
            
            # Print summary
            return self.print_summary()
            
        finally:
            if self.live_exchange:
                await self.live_exchange.close()


async def main():
    """Main entry point."""
    demo = LivePaperTradingDemo(symbol="SOLUSDT", initial_capital=1000.0)
    results = await demo.run()
    return results


if __name__ == "__main__":
    asyncio.run(main())
